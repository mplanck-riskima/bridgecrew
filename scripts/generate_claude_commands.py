#!/usr/bin/env python3
"""
Generate Claude CLI slash command files from docs/feature-lifecycle.md.

Usage:
    python scripts/generate_claude_commands.py [--output-dir DIR] [--lifecycle-doc PATH]

Defaults:
    --output-dir     ~/.claude/commands
    --lifecycle-doc  docs/feature-lifecycle.md (relative to repo root)
"""
import argparse
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def extract_section(text: str, heading: str) -> str:
    """Extract a ## section from markdown text. Returns the section body (no heading line)."""
    pattern = re.compile(
        rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def load_lifecycle_doc(path: Path) -> str:
    if not path.exists():
        print(f"ERROR: lifecycle doc not found at {path}", file=sys.stderr)
        sys.exit(1)
    return path.read_text(encoding="utf-8")


# ── Command templates ─────────────────────────────────────────────────────────
# Each template references {SUMMARY_FORMAT} and {SNAKE_RULE} which are
# injected at render time.

_START_FEATURE = """\
Start a new feature for the current project.

**Feature name:** $ARGUMENTS

## Steps

1. **Identify the project directory** — use the current working directory (`$PWD`).

2. **Read the feature index** — open `.claude/features.json` in `$PWD`.
   If the file does not exist, treat it as `{{"current_feature": null, "sessions": {{}}}}`.

3. **Auto-complete any active feature** — if `current_feature` is not null:
   - Load `.claude/features/<snake_name>.json` for that feature
   - Set `"status": "completed"` and `"completed_at"` to the current UTC ISO timestamp
   - Write the file back
   - Generate a summary per the Summary Format below and write it to `features/<feature-name>.md`
   - Set `"current_feature"` to null in `.claude/features.json`
   - Tell the user which feature was auto-completed

4. **Filename conversion** — convert `$ARGUMENTS` to snake_case:
   {SNAKE_RULE}

5. **Create `.claude/features/` directory** if it does not exist.

6. **Write `.claude/features/<snake_name>.json`:**
   ```json
   {{
     "name": "$ARGUMENTS",
     "status": "active",
     "session_id": "<generate a new UUID>",
     "subdir": null,
     "started_at": "<current UTC ISO timestamp, e.g. 2026-04-05T10:00:00+00:00>",
     "completed_at": null,
     "sessions": [],
     "total_cost_usd": 0.0,
     "total_input_tokens": 0,
     "total_output_tokens": 0,
     "bridgecrew_feature_id": null
   }}
   ```

7. **Update `.claude/features.json`** — set `"current_feature"` to `"$ARGUMENTS"`.
   Preserve the existing `"sessions"` field; do not overwrite it.

8. **Create stub feature doc** — if `features/$ARGUMENTS.md` does not exist, create it:
   ```markdown
   # $ARGUMENTS

   **Status:** Active
   **Started:** <today's date YYYY-MM-DD>

   ## Goal

   _Describe what this feature is trying to accomplish._

   ## Progress

   _Notes will be added here as work progresses._
   ```
   Create the `features/` directory first if it does not exist.

9. **Report** — confirm to the user: "Feature **`$ARGUMENTS`** started."
   If a feature was auto-completed, include: "Auto-completed **`<name>`** and wrote summary."

---

## Summary Format

{SUMMARY_FORMAT}
"""

_COMPLETE_FEATURE = """\
Complete the currently active feature for the project in the current working directory.

## Steps

1. **Identify the project directory** — use the current working directory (`$PWD`).

2. **Read the feature index** — open `.claude/features.json` in `$PWD`.
   If `current_feature` is null or the file does not exist, tell the user
   "No active feature to complete." and stop.

3. **Load the feature record** — convert `current_feature` to snake_case (see below),
   load `.claude/features/<snake_name>.json`.
   If the file does not exist, tell the user and stop.

4. **Mark as completed:**
   - Set `"status"` to `"completed"`
   - Set `"completed_at"` to the current UTC ISO timestamp
   - Write the file back

5. **Generate summary** per the Summary Format below and write to
   `features/<feature-name>.md`.

6. **Update the index** — set `"current_feature"` to null in `.claude/features.json`.
   Preserve the `"sessions"` field.

7. **Report** — "Feature **`<name>`** completed. Summary written to `features/<name>.md`."

**Filename conversion** (snake_case):
{SNAKE_RULE}

---

## Summary Format

{SUMMARY_FORMAT}
"""

_RESUME_FEATURE = """\
Resume a feature for the project in the current working directory.

## Steps

1. **Identify the project directory** — use the current working directory (`$PWD`).

2. **List all features** — scan `.claude/features/*.json`. For each file, read `name` and `status`.
   If no features exist, tell the user "No features found. Use `/start-feature <name>` to create one." and stop.

3. **Display the list** to the user in this format:
   ```
   Features for this project:
     1. my-feature [active] <- current
     2. old-feature [completed]
     3. another [completed]
   ```
   Ask the user which feature to resume (by name or number).
   Wait for their response before continuing.

4. **Check for an active feature** (other than the one being resumed):
   - Load `.claude/features.json`
   - If `current_feature` is not null and is different from the chosen feature:
     - Load the active feature's JSON
     - Set `"status": "completed"`, `"completed_at"`: now
     - Write it back
     - Generate a summary per the Summary Format below
     - Tell the user which feature was auto-completed

5. **Resume the chosen feature:**
   - Load its JSON
   - Set `"status": "active"`, clear `"completed_at"` (set to null)
   - Write it back
   - Update `"current_feature"` in `.claude/features.json` to the feature's name

6. **Report** — "Resumed feature **`<name>`**."

**Filename conversion** (snake_case):
{SNAKE_RULE}

---

## Summary Format

{SUMMARY_FORMAT}
"""

_LIST_FEATURES = """\
List all features for the project in the current working directory.

## Steps

1. **Identify the project directory** — use the current working directory (`$PWD`).

2. **Read the feature index** — open `.claude/features.json`. Note `current_feature`.
   If the file does not exist, treat `current_feature` as null.

3. **Scan per-feature files** — read all `.json` files in `.claude/features/`.
   For each, extract: `name`, `status`, `subdir`, `started_at`, `completed_at`.

4. **Display in a monospace block** (sort: active first, then by started_at descending):

   ```
   Features — <project dir basename>
   ─────────────────────────────────────────────
   Name                Status      Started
   ─────────────────────────────────────────────
   my-feature          active      2026-04-01  <- current
   old-feature         completed   2026-03-15
   another             completed   2026-03-01
   ─────────────────────────────────────────────
   Total: 3  Active: 1
   ```

   If no features exist: "No features yet. Use `/start-feature <name>` to create one."
"""

_DISCARD_FEATURE = """\
Discard a feature from the project in the current working directory.
This removes its tracking record, archives its doc, and strips it from CLAUDE.md.

## Steps

1. **Identify the project directory** — use the current working directory (`$PWD`).

2. **List all features** — scan `.claude/features/*.json`. If none, tell the user
   "No features to discard." and stop.

3. **Display the list** and ask the user which feature to discard.
   Wait for their response. Ask for confirmation before proceeding:
   "Discard **`<name>`**? This cannot be undone. (yes/no)"

4. **Archive the feature doc** — if `features/<name>.md` exists:
   - Create `features/_archived/` if it does not exist
   - Move `features/<name>.md` to `features/_archived/<name>.md`

5. **Delete the feature record** — delete `.claude/features/<snake_name>.json`.

6. **Update the index** — in `.claude/features.json`:
   - If `current_feature` equals this feature's name, set it to null
   - Remove any sessions entries whose `"feature"` value matches this feature's name

7. **Strip from CLAUDE.md** — in `$PWD/CLAUDE.md`, find the `## Features` section
   and remove any bullet line that starts with `**<name>**` (case-insensitive).
   Only modify the file if such a line is found.

8. **Report** what was done:
   - "Feature **`<name>`** discarded."
   - "Archived: `features/_archived/<name>.md`" (if the doc existed)
   - "Removed from CLAUDE.md" (if a bullet was removed)

**Filename conversion** (snake_case):
{SNAKE_RULE}
"""

COMMANDS: dict[str, str] = {
    "start-feature": _START_FEATURE,
    "complete-feature": _COMPLETE_FEATURE,
    "resume-feature": _RESUME_FEATURE,
    "list-features": _LIST_FEATURES,
    "discard-feature": _DISCARD_FEATURE,
}

_SNAKE_RULE = (
    "lowercase; replace & with 'and'; replace hyphens/spaces with _; "
    "remove non-alphanumeric except _; collapse __; strip leading/trailing _. "
    'Example: "my-feature" → "my_feature", "Bugs & Fixes" → "bugs_and_fixes"'
)


def render_command(template: str, summary_format: str) -> str:
    """Inject lifecycle doc sections into a command template."""
    return template.format(
        SUMMARY_FORMAT=summary_format,
        SNAKE_RULE=_SNAKE_RULE,
    )


def generate(output_dir: Path, lifecycle_doc_path: Path) -> list[str]:
    """Generate all command files. Returns list of written file paths."""
    lifecycle_text = load_lifecycle_doc(lifecycle_doc_path)
    summary_format = extract_section(lifecycle_text, "Summary Format")

    output_dir.mkdir(parents=True, exist_ok=True)
    written = []

    for name, template in COMMANDS.items():
        content = render_command(template, summary_format)
        out_path = output_dir / f"{name}.md"
        out_path.write_text(content, encoding="utf-8")
        written.append(str(out_path))

    return written


def build_claude_md_block(lifecycle_text: str) -> str:
    """Build the auto-generated block to inject into ~/.claude/CLAUDE.md."""
    overview = extract_section(lifecycle_text, "Overview")
    workflow = extract_section(lifecycle_text, "Workflow")
    state_files = extract_section(lifecycle_text, "State Files")
    return (
        "# BEGIN: feature-lifecycle (auto-generated)\n"
        "# Do not edit this block manually — re-run setup-claude-pc.sh to update.\n\n"
        "## Feature Lifecycle\n\n"
        f"{overview}\n\n"
        "### State Files\n\n"
        f"{state_files}\n\n"
        "### Workflow Summary\n\n"
        f"{workflow}\n"
        "# END: feature-lifecycle"
    )


def merge_claude_md(claude_md_path: Path, block: str) -> None:
    """Write or merge the feature-lifecycle block into ~/.claude/CLAUDE.md."""
    marker_start = "# BEGIN: feature-lifecycle"
    marker_end = "# END: feature-lifecycle"

    if claude_md_path.exists():
        existing = claude_md_path.read_text(encoding="utf-8")
        if marker_start in existing:
            pattern = re.compile(
                rf"{re.escape(marker_start)}.*?{re.escape(marker_end)}",
                re.DOTALL,
            )
            new_content = pattern.sub(block, existing)
        else:
            new_content = existing.rstrip("\n") + "\n\n" + block + "\n"
    else:
        claude_md_path.parent.mkdir(parents=True, exist_ok=True)
        new_content = block + "\n"

    claude_md_path.write_text(new_content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.home() / ".claude" / "commands",
        help="Directory to write command .md files (default: ~/.claude/commands)",
    )
    parser.add_argument(
        "--lifecycle-doc",
        type=Path,
        default=REPO_ROOT / "docs" / "feature-lifecycle.md",
        help="Path to feature-lifecycle.md",
    )
    parser.add_argument(
        "--claude-md",
        type=Path,
        default=Path.home() / ".claude" / "CLAUDE.md",
        help="Path to user-level CLAUDE.md to merge into",
    )
    parser.add_argument(
        "--skip-claude-md",
        action="store_true",
        help="Skip writing/merging ~/.claude/CLAUDE.md",
    )
    args = parser.parse_args()

    print(f"Lifecycle doc: {args.lifecycle_doc}")
    print(f"Output dir:    {args.output_dir}")

    lifecycle_text = load_lifecycle_doc(args.lifecycle_doc)
    written = generate(args.output_dir, args.lifecycle_doc)

    print(f"\nGenerated {len(written)} command files:")
    for path in written:
        print(f"  {path}")

    if not args.skip_claude_md:
        block = build_claude_md_block(lifecycle_text)
        merge_claude_md(args.claude_md, block)
        print(f"\nMerged feature-lifecycle block into: {args.claude_md}")

    print("\nDone.")


if __name__ == "__main__":
    main()
