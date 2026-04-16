#!/usr/bin/env python3
"""
Two-pass migration for the features collection:

  Pass 1 — Rename feature_id from ULIDs to project_name:feature_name composite
            keys, and cascade the rename to the cost_log collection.
            (Skipped automatically for features already using the composite format.)

  Pass 2 — Back-fill summary and markdown_content for features that are missing
            them by reading the corresponding .md file from the project's
            features/ directory on disk.

Usage:
    MONGODB_URI=<uri> python migrate_feature_ids.py --workspace /path/to/workspace
    MONGODB_URI=<uri> MONGODB_DATABASE=bridgecrew_prod python migrate_feature_ids.py \\
        --workspace /path/to/workspace --dry-run

    # Skip one of the passes:
    python migrate_feature_ids.py --workspace /path/to/workspace --skip-id-migration
    python migrate_feature_ids.py --skip-summary-backfill
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from pymongo import MongoClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_summary(markdown: str) -> str:
    """Return the text under the first '## Summary' heading, stripped."""
    match = re.search(r"^##\s+Summary\s*\n(.*?)(?=^##|\Z)", markdown, re.MULTILINE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def _find_feature_md(workspace: Path, project_name: str, feature_name: str) -> Path | None:
    """
    Look for {workspace}/{project_name}/features/{feature_name}.md.
    Tries the raw name, then a kebab-cased variant, then a snake-cased variant.
    """
    base = workspace / project_name / "features"
    if not base.exists():
        return None

    candidates = [
        feature_name + ".md",
        feature_name.lower().replace(" ", "-") + ".md",
        feature_name.lower().replace(" ", "_") + ".md",
    ]
    for name in candidates:
        p = base / name
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Pass 1: ID migration
# ---------------------------------------------------------------------------

def migrate_ids(features_col, projects_col, cost_log_col, dry_run: bool) -> None:
    print("--- Pass 1: Feature ID migration ---\n")

    projects = {
        p["project_id"]: p["name"]
        for p in projects_col.find({}, {"project_id": 1, "name": 1, "_id": 0})
        if "project_id" in p and "name" in p
    }
    print(f"Found {len(projects)} projects.")

    features = list(features_col.find({}, {"_id": 0}))
    print(f"Found {len(features)} features to inspect.\n")

    updated = skipped = errors = 0

    for feat in features:
        old_id: str = feat.get("feature_id", "")
        feature_name: str = feat.get("name", "")
        project_id: str = feat.get("project_id", "")

        if ":" in old_id:
            print(f"  SKIP  (already composite) {old_id}")
            skipped += 1
            continue

        project_name = projects.get(project_id, "")
        if not project_name:
            print(f"  ERROR no project for project_id={project_id!r}, feature_id={old_id!r}")
            errors += 1
            continue

        if not feature_name:
            print(f"  ERROR feature has no name, feature_id={old_id!r}")
            errors += 1
            continue

        new_id = f"{project_name}:{feature_name}"

        if old_id == new_id:
            print(f"  SKIP  (already correct) {old_id}")
            skipped += 1
            continue

        collision = features_col.find_one({"feature_id": new_id}, {"_id": 0})
        if collision:
            print(f"  ERROR collision: {new_id!r} already exists — skipping {old_id!r}")
            errors += 1
            continue

        cost_count = cost_log_col.count_documents({"feature_id": old_id})
        print(f"  UPDATE {old_id!r}")
        print(f"      -> {new_id!r}  (cost_log rows: {cost_count})")

        if not dry_run:
            features_col.update_one({"feature_id": old_id}, {"$set": {"feature_id": new_id}})
            if cost_count:
                cost_log_col.update_many({"feature_id": old_id}, {"$set": {"feature_id": new_id}})

        updated += 1

    print(f"\nPass 1 done. Updated: {updated}  Skipped: {skipped}  Errors: {errors}\n")


# ---------------------------------------------------------------------------
# Pass 2: Summary / markdown_content backfill
# ---------------------------------------------------------------------------

def backfill_summaries(features_col, projects_col, workspace: Path, dry_run: bool) -> None:
    print("--- Pass 2: Summary backfill from feature markdown files ---\n")

    projects = {
        p["project_id"]: p["name"]
        for p in projects_col.find({}, {"project_id": 1, "name": 1, "_id": 0})
        if "project_id" in p and "name" in p
    }

    # Only features with no summary AND no markdown_content
    query = {
        "$or": [
            {"summary": None},
            {"summary": {"$exists": False}},
        ],
        "$or": [  # noqa: F601  (intentional duplicate key — MongoDB evaluates last $or)
            {"markdown_content": None},
            {"markdown_content": {"$exists": False}},
        ],
    }
    # Simpler: fetch all and filter in Python to avoid MongoDB $or quirk with duplicate keys
    features = [
        f for f in features_col.find({}, {"_id": 0})
        if not f.get("summary") and not f.get("markdown_content")
    ]
    print(f"Found {len(features)} features without summary/markdown_content.\n")

    updated = skipped = errors = 0

    for feat in features:
        feature_id: str = feat.get("feature_id", "")
        feature_name: str = feat.get("name", "")
        project_id: str = feat.get("project_id", "")

        project_name = projects.get(project_id, "")
        if not project_name:
            print(f"  SKIP  no project for {feature_id!r}")
            skipped += 1
            continue

        md_path = _find_feature_md(workspace, project_name, feature_name)
        if md_path is None:
            print(f"  SKIP  no .md file found for {feature_id!r}")
            skipped += 1
            continue

        markdown = md_path.read_text(encoding="utf-8")
        summary = _extract_summary(markdown)

        print(f"  BACKFILL {feature_id!r}")
        print(f"           md: {md_path.relative_to(workspace)}")
        if summary:
            print(f"           summary: {summary[:80]}{'…' if len(summary) > 80 else ''}")
        else:
            print(f"           summary: (none extracted — will set markdown_content only)")

        if not dry_run:
            patch: dict = {"markdown_content": markdown}
            if summary:
                patch["summary"] = summary
            features_col.update_one({"feature_id": feature_id}, {"$set": patch})

        updated += 1

    print(f"\nPass 2 done. Updated: {updated}  Skipped: {skipped}  Errors: {errors}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate feature IDs and back-fill summaries from markdown files."
    )
    parser.add_argument(
        "--workspace",
        default=os.environ.get("WORKSPACE", ""),
        help="Path to the workspace root (parent of all project dirs). "
             "Required for --pass-summary. Can also be set via WORKSPACE env var.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing.")
    parser.add_argument("--skip-id-migration", action="store_true", help="Skip Pass 1.")
    parser.add_argument("--skip-summary-backfill", action="store_true", help="Skip Pass 2.")
    args = parser.parse_args()

    uri = os.environ.get("MONGODB_URI", "")
    db_name = os.environ.get("MONGODB_DATABASE", "bridgecrew_dev")

    if not uri:
        print("ERROR: MONGODB_URI environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"=== Feature Migration [{mode}] — database: {db_name} ===\n")

    client: MongoClient = MongoClient(uri)
    db = client[db_name]
    features_col = db["features"]
    projects_col = db["projects"]
    cost_log_col = db["cost_log"]

    if not args.skip_id_migration:
        migrate_ids(features_col, projects_col, cost_log_col, args.dry_run)

    if not args.skip_summary_backfill:
        if not args.workspace:
            print("ERROR: --workspace is required for summary backfill. "
                  "Use --skip-summary-backfill to skip it.", file=sys.stderr)
            sys.exit(1)
        workspace = Path(args.workspace)
        if not workspace.exists():
            print(f"ERROR: workspace path does not exist: {workspace}", file=sys.stderr)
            sys.exit(1)
        backfill_summaries(features_col, projects_col, workspace, args.dry_run)

    if args.dry_run:
        print("(No changes were written — re-run without --dry-run to apply.)")


if __name__ == "__main__":
    main()
