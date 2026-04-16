#!/usr/bin/env python3
"""
Migrate feature_id values in MongoDB from ULIDs to project_name:feature_name
composite keys, and cascade the rename to the cost_log collection.

Usage:
    MONGODB_URI=<uri> python migrate_feature_ids.py
    MONGODB_URI=<uri> MONGODB_DATABASE=bridgecrew_prod python migrate_feature_ids.py
    python migrate_feature_ids.py --dry-run

Features whose feature_id already contains a colon are assumed to already
use the composite-key format and are skipped.
"""

from __future__ import annotations

import argparse
import os
import sys

from pymongo import MongoClient


def main(dry_run: bool) -> None:
    uri = os.environ.get("MONGODB_URI", "")
    db_name = os.environ.get("MONGODB_DATABASE", "bridgecrew_dev")

    if not uri:
        print("ERROR: MONGODB_URI environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    client: MongoClient = MongoClient(uri)
    db = client[db_name]
    features_col = db["features"]
    projects_col = db["projects"]
    cost_log_col = db["cost_log"]

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"=== Feature ID Migration [{mode}] — database: {db_name} ===\n")

    # Build project_id → name map
    projects = {
        p["project_id"]: p["name"]
        for p in projects_col.find({}, {"project_id": 1, "name": 1, "_id": 0})
        if "project_id" in p and "name" in p
    }
    print(f"Found {len(projects)} projects.\n")

    features = list(features_col.find({}, {"_id": 0}))
    print(f"Found {len(features)} features to inspect.\n")

    updated = skipped = errors = 0

    for feat in features:
        old_id: str = feat.get("feature_id", "")
        feature_name: str = feat.get("name", "")
        project_id: str = feat.get("project_id", "")

        # Already using composite-key format — skip
        if ":" in old_id:
            print(f"  SKIP  (already composite) {old_id}")
            skipped += 1
            continue

        project_name = projects.get(project_id, "")
        if not project_name:
            print(f"  ERROR no project found for project_id={project_id!r}, feature_id={old_id!r}")
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

        # Collision check
        collision = features_col.find_one({"feature_id": new_id}, {"_id": 0})
        if collision:
            print(f"  ERROR collision: {new_id!r} already exists — skipping {old_id!r}")
            errors += 1
            continue

        cost_count = cost_log_col.count_documents({"feature_id": old_id})

        print(f"  UPDATE {old_id!r}")
        print(f"      -> {new_id!r}  (cost_log rows: {cost_count})")

        if not dry_run:
            features_col.update_one(
                {"feature_id": old_id},
                {"$set": {"feature_id": new_id}},
            )
            if cost_count:
                cost_log_col.update_many(
                    {"feature_id": old_id},
                    {"$set": {"feature_id": new_id}},
                )

        updated += 1

    print(f"\n=== Done. Updated: {updated}  Skipped: {skipped}  Errors: {errors} ===")
    if dry_run:
        print("(No changes were written — re-run without --dry-run to apply.)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate feature_id to composite keys.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without writing to the database.",
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run)
