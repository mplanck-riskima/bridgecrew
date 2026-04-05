# PC Feature Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `setup-claude-pc.sh` + a generator script that installs five Claude slash commands to `~/.claude/commands/`, giving Claude CLI on any PC the same feature tracking workflow as the Discord bot.

**Architecture:** A canonical `docs/feature-lifecycle.md` describes the lifecycle rules. A pure-Python generator reads that doc, renders five command markdown files, and writes them to `~/.claude/commands/`. A shell setup script runs the generator and merges feature rules into `~/.claude/CLAUDE.md`. No bot code changes — feature state already lives in `<project>/.claude/features/`.

**Tech Stack:** Python 3 stdlib only (pathlib, json, re, argparse, uuid), Bash

---

## Important: State Format

Before reading the tasks, understand the exact state the commands must read/write — this must match the bot's format exactly.

**Feature index** at `<project>/.claude/features.json`:
```json
{"current_feature": "my-feature", "sessions": {}}
```

**Per-feature record** at `<project>/.claude/features/<snake_name>.json`:
```json
{
  "name": "my-feature",
  "status": "active",
  "session_id": "<uuid>",
  "subdir": null,
  "started_at": "2026-04-05T10:00:00Z",
  "completed_at": null,
  "sessions": [],
  "total_cost_usd": 0.0,
  "total_input_tokens": 0,
  "total_output_tokens": 0,
  "bridgecrew_feature_id": null
}
```

**Filename convention** — `feature_name_to_filename()` in `core/state.py:68`:
- Lowercase, `&` → `and`, hyphens/spaces → `_`, strip non-alphanumeric, collapse `__`
- Examples: `"my-feature"` → `"my_feature"`, `"Bugs & Fixes"` → `"bugs_and_fixes"`

---

## Task 1: Write `docs/feature-lifecycle.md`

**Files:**
- Create: `docs/feature-lifecycle.md`

This is the source-of-truth doc the generator reads. It must contain a `## Summary Format` section (which gets injected into commands) and a `## State Files` section (injected into all commands for reference).

- [ ] **Step 1: Create the lifecycle doc**

```markdown
# Feature Lifecycle

This document is the canonical source of truth for how features are tracked
across all projects in this workspace. It is read by `scripts/generate_claude_commands.py`
to render the Claude CLI slash commands installed by `setup-claude-pc.sh`.

## Overview

A **feature** is a named unit of work on a project. At most one feature is active
per project at any time. When you start or resume a feature, any currently active
feature is automatically completed first (no paused state). Completing a feature
generates a written summary.

## Status Values

- `active` — currently being worked on (only one per project)
- `completed` — finished; a summary has been written to `features/<name>.md`
- `discarded` — abandoned; removed from tracking, doc archived

## State Files

Feature state lives in `<project>/.claude/`. This directory is shared between
the Discord bot and Claude CLI — both read and write the same files.

**Feature index** at `<project>/.claude/features.json`:
```json
{"current_feature": "my-feature", "sessions": {}}
```
- `current_feature`: name of the active feature, or null
- `sessions`: map of session UUIDs to feature names (managed by the bot; leave unchanged from CLI)

**Per-feature record** at `<project>/.claude/features/<snake_name>.json`:
```json
{
  "name": "my-feature",
  "status": "active",
  "session_id": "<uuid>",
  "subdir": null,
  "started_at": "2026-04-05T10:00:00+00:00",
  "completed_at": null,
  "sessions": [],
  "total_cost_usd": 0.0,
  "total_input_tokens": 0,
  "total_output_tokens": 0,
  "bridgecrew_feature_id": null
}
```

**Filename convention** — convert feature name to snake_case:
1. Lowercase the name
2. Replace `&` with `and`
3. Replace hyphens and spaces with `_`
4. Remove all characters that are not alphanumeric or `_`
5. Collapse consecutive `_` into one; strip leading/trailing `_`
6. If empty, use `unnamed`

Examples:
- `"my-feature"` → `"my_feature"`
- `"Bugs & Fixes"` → `"bugs_and_fixes"`
- `"Star-trek-personas"` → `"star_trek_personas"`

## Summary Format

When a feature is completed (via `/complete-feature` or auto-complete when starting/resuming another feature), write a summary to `features/<feature-name>.md`.

To generate the summary:
1. Read the feature's `started_at` from its JSON file (ISO timestamp)
2. Run: `git log --oneline --since="<started_at>" 2>/dev/null` to list commits made during this feature
3. Run: `git diff $(git log --since="<started_at>" --format="%H" | tail -1)^ HEAD -- . 2>/dev/null` to get the full diff (fall back to `git diff HEAD~5..HEAD` if the above fails)
4. Read the existing `features/<feature-name>.md` if it exists (to preserve any goal description)
5. Write an updated `features/<feature-name>.md`:

```markdown
# <feature-name>

**Status:** Completed
**Started:** <started_at date, formatted as YYYY-MM-DD>
**Completed:** <completed_at date, formatted as YYYY-MM-DD>

## Goal

<What was this feature trying to accomplish? Preserve existing goal text if present, otherwise infer from the commits and diff.>

## What Was Built

<Prose summary of the changes made — 2-5 sentences describing the main work done.>

## Key Changes

<Bullet list of the most important files/components changed and why.>

## Commits

<Output of git log --oneline --since="<started_at>", or "No commits recorded" if none.>
```

If `features/` directory does not exist in the project, create it first.

## Workflow

### Starting a Feature

1. Check `.claude/features.json` for an active feature
2. If one exists, auto-complete it (set status=completed, completed_at=now, write summary)
3. Create the new feature JSON with status=active
4. Update `features.json` current_feature
5. Create a stub `features/<name>.md` if it does not exist

### Completing a Feature

1. Read `.claude/features.json` to find the current active feature
2. Load its JSON, set status=completed, completed_at=now
3. Write summary to `features/<name>.md`
4. Set current_feature=null in `features.json`

### Resuming a Feature

1. List all features (read all `.json` files in `.claude/features/`)
2. If an active feature exists (other than the one being resumed), auto-complete it
3. Set the chosen feature's status=active, clear completed_at
4. Update `features.json` current_feature

### Discarding a Feature

1. Load the feature JSON
2. If `features/<name>.md` exists, move it to `features/_archived/<name>.md`
3. Delete the feature JSON from `.claude/features/`
4. Remove it from `features.json` (set current_feature=null if it was active)
5. In `CLAUDE.md`, remove any bullet that starts with `**<name>**` under `## Features`
```

- [ ] **Step 2: Commit**

```bash
git add docs/feature-lifecycle.md
git commit -m "docs: add canonical feature lifecycle doc"
```

---

## Task 2: Write the generator script

**Files:**
- Create: `scripts/generate_claude_commands.py`
- Create: `scripts/__init__.py` (empty, so the script is importable for tests)

The generator reads `docs/feature-lifecycle.md`, extracts the `## Summary Format` and `## State Files` sections, and renders five command files. It writes to `~/.claude/commands/` by default, or a custom directory if `--output-dir` is passed.

- [ ] **Step 1: Create `scripts/__init__.py`**

```python
```
(empty file)

- [ ] **Step 2: Write the failing test** (skip ahead to Task 3, then return here — or write test first)

Actually, follow TDD: write tests in Task 3 first, then come back here. The step ordering in this plan intentionally puts tests before implementation.

- [ ] **Step 3: Create `scripts/generate_claude_commands.py`**

```python
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


def _snake(name: str) -> str:
    """Describe the snake_case conversion so commands can explain it inline."""
    return (
        "lowercase; replace & with 'and'; replace hyphens/spaces with _; "
        "remove non-alphanumeric except _; collapse __; strip leading/trailing _"
    )


# ── Command templates ─────────────────────────────────────────────────────────
# Each template may reference {STATE_FILES} and {SUMMARY_FORMAT} which are
# extracted from the lifecycle doc and injected at render time.

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

2. **List all features** — scan `.claude/features/*.json` (skip `feature-index.json`
   if present). For each file, read `name` and `status`. If no features exist,
   tell the user "No features found. Use `/start-feature <name>` to create one." and stop.

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


def render_command(template: str, summary_format: str) -> str:
    """Inject lifecycle doc sections into a command template."""
    snake_rule = (
        "lowercase; replace & with 'and'; replace hyphens/spaces with _; "
        "remove non-alphanumeric except _; collapse __; strip leading/trailing _. "
        "Example: \"my-feature\" → \"my_feature\", \"Bugs & Fixes\" → \"bugs_and_fixes\""
    )
    return template.format(
        SUMMARY_FORMAT=summary_format,
        SNAKE_RULE=snake_rule,
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
            # Replace the existing block
            pattern = re.compile(
                rf"{re.escape(marker_start)}.*?{re.escape(marker_end)}",
                re.DOTALL,
            )
            new_content = pattern.sub(block, existing)
        else:
            # Append the block
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
```

- [ ] **Step 4: Commit**

```bash
git add scripts/__init__.py scripts/generate_claude_commands.py
git commit -m "feat: add Claude command generator script"
```

---

## Task 3: Write tests for the generator

**Files:**
- Create: `tests/bot/test_generate_claude_commands.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for scripts/generate_claude_commands.py."""
import json
import re
from pathlib import Path

import pytest

from scripts.generate_claude_commands import (
    extract_section,
    render_command,
    generate,
    build_claude_md_block,
    merge_claude_md,
    COMMANDS,
)

SAMPLE_LIFECYCLE = """\
# Feature Lifecycle

## Overview

A feature is a named unit of work. At most one is active per project.

## State Files

Feature index at `.claude/features.json`.
Per-feature at `.claude/features/<snake_name>.json`.

## Summary Format

Write a summary to `features/<name>.md` with sections: Goal, What Was Built,
Key Changes, Commits.

## Workflow

Start, complete, resume, discard.
"""


class TestExtractSection:
    def test_extracts_summary_format(self):
        result = extract_section(SAMPLE_LIFECYCLE, "Summary Format")
        assert "Write a summary" in result
        assert "Goal" in result

    def test_extracts_overview(self):
        result = extract_section(SAMPLE_LIFECYCLE, "Overview")
        assert "named unit of work" in result

    def test_missing_section_returns_empty(self):
        result = extract_section(SAMPLE_LIFECYCLE, "Nonexistent Section")
        assert result == ""

    def test_does_not_include_next_section(self):
        result = extract_section(SAMPLE_LIFECYCLE, "Overview")
        assert "State Files" not in result


class TestRenderCommand:
    def test_injects_summary_format(self):
        template = "Instructions here.\n\n## Summary Format\n\n{SUMMARY_FORMAT}\n"
        rendered = render_command(template, "Write the summary like THIS.")
        assert "Write the summary like THIS." in rendered

    def test_injects_snake_rule(self):
        template = "Rule: {SNAKE_RULE}"
        rendered = render_command(template, "")
        assert "my_feature" in rendered  # example in the rule

    def test_no_unresolved_placeholders(self):
        for name, template in COMMANDS.items():
            rendered = render_command(template, "Summary format text.")
            assert "{SUMMARY_FORMAT}" not in rendered, f"Unresolved placeholder in {name}"
            assert "{SNAKE_RULE}" not in rendered, f"Unresolved placeholder in {name}"


class TestGenerate:
    def test_generates_all_five_commands(self, tmp_path):
        lifecycle = tmp_path / "feature-lifecycle.md"
        lifecycle.write_text(SAMPLE_LIFECYCLE, encoding="utf-8")
        out_dir = tmp_path / "commands"

        written = generate(out_dir, lifecycle)

        assert len(written) == 5
        expected = {
            "start-feature.md",
            "complete-feature.md",
            "resume-feature.md",
            "list-features.md",
            "discard-feature.md",
        }
        assert {Path(p).name for p in written} == expected

    def test_output_files_contain_summary_format(self, tmp_path):
        lifecycle = tmp_path / "feature-lifecycle.md"
        lifecycle.write_text(SAMPLE_LIFECYCLE, encoding="utf-8")
        out_dir = tmp_path / "commands"
        generate(out_dir, lifecycle)

        # Commands that generate summaries should have the summary format injected
        for cmd in ("start-feature.md", "complete-feature.md", "resume-feature.md"):
            content = (out_dir / cmd).read_text()
            assert "Write a summary" in content, f"{cmd} missing summary format"

    def test_idempotent(self, tmp_path):
        lifecycle = tmp_path / "feature-lifecycle.md"
        lifecycle.write_text(SAMPLE_LIFECYCLE, encoding="utf-8")
        out_dir = tmp_path / "commands"

        generate(out_dir, lifecycle)
        first = {f.name: f.read_text() for f in out_dir.glob("*.md")}

        generate(out_dir, lifecycle)
        second = {f.name: f.read_text() for f in out_dir.glob("*.md")}

        assert first == second

    def test_creates_output_dir(self, tmp_path):
        lifecycle = tmp_path / "feature-lifecycle.md"
        lifecycle.write_text(SAMPLE_LIFECYCLE, encoding="utf-8")
        out_dir = tmp_path / "nested" / "commands"
        assert not out_dir.exists()

        generate(out_dir, lifecycle)

        assert out_dir.exists()

    def test_missing_lifecycle_doc_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            generate(tmp_path / "commands", tmp_path / "nonexistent.md")


class TestBuildClaudeMdBlock:
    def test_contains_markers(self):
        block = build_claude_md_block(SAMPLE_LIFECYCLE)
        assert "# BEGIN: feature-lifecycle" in block
        assert "# END: feature-lifecycle" in block

    def test_contains_overview(self):
        block = build_claude_md_block(SAMPLE_LIFECYCLE)
        assert "named unit of work" in block

    def test_contains_workflow(self):
        block = build_claude_md_block(SAMPLE_LIFECYCLE)
        assert "Start, complete, resume, discard" in block


class TestMergeClaudeMd:
    def test_creates_file_if_missing(self, tmp_path):
        path = tmp_path / "CLAUDE.md"
        merge_claude_md(path, "# BEGIN: feature-lifecycle\nblock\n# END: feature-lifecycle")
        assert path.exists()
        assert "block" in path.read_text()

    def test_appends_to_existing_file(self, tmp_path):
        path = tmp_path / "CLAUDE.md"
        path.write_text("# My existing instructions\n\nSome content.\n")
        merge_claude_md(path, "# BEGIN: feature-lifecycle\nblock\n# END: feature-lifecycle")
        content = path.read_text()
        assert "My existing instructions" in content
        assert "block" in content

    def test_replaces_existing_block(self, tmp_path):
        path = tmp_path / "CLAUDE.md"
        path.write_text(
            "# Custom stuff\n\n"
            "# BEGIN: feature-lifecycle\nold block content\n# END: feature-lifecycle\n\n"
            "# More custom stuff\n"
        )
        merge_claude_md(path, "# BEGIN: feature-lifecycle\nnew block\n# END: feature-lifecycle")
        content = path.read_text()
        assert "old block content" not in content
        assert "new block" in content
        assert "Custom stuff" in content
        assert "More custom stuff" in content

    def test_preserves_content_outside_block(self, tmp_path):
        path = tmp_path / "CLAUDE.md"
        path.write_text(
            "# Before\n\n"
            "# BEGIN: feature-lifecycle\nold\n# END: feature-lifecycle\n\n"
            "# After\n"
        )
        merge_claude_md(path, "# BEGIN: feature-lifecycle\nnew\n# END: feature-lifecycle")
        content = path.read_text()
        assert "# Before" in content
        assert "# After" in content
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd M:/bridgecrew
source venv/Scripts/activate
pytest tests/bot/test_generate_claude_commands.py -v 2>&1 | head -40
```

Expected: ImportError or collection errors (module not yet importable from tests).

- [ ] **Step 3: Fix import path if needed**

If `scripts/` is not on the Python path, add a `conftest.py` at the repo root:

Check if `conftest.py` exists at repo root first:
```bash
ls M:/bridgecrew/conftest.py 2>/dev/null || echo "missing"
```

If missing, create `conftest.py`:
```python
import sys
from pathlib import Path

# Ensure repo root is on the path so `scripts/` is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
```

If it exists, add the `sys.path.insert` line to it (only if not already present).

- [ ] **Step 4: Run tests again — expect failures for unimplemented functions**

```bash
pytest tests/bot/test_generate_claude_commands.py -v 2>&1 | head -60
```

Expected: ImportError resolved; test failures about missing implementation.

- [ ] **Step 5: Run tests after implementing Task 2 to verify they pass**

```bash
pytest tests/bot/test_generate_claude_commands.py -v
```

Expected output:
```
PASSED tests/bot/test_generate_claude_commands.py::TestExtractSection::test_extracts_summary_format
PASSED tests/bot/test_generate_claude_commands.py::TestExtractSection::test_extracts_overview
PASSED tests/bot/test_generate_claude_commands.py::TestExtractSection::test_missing_section_returns_empty
PASSED tests/bot/test_generate_claude_commands.py::TestExtractSection::test_does_not_include_next_section
PASSED tests/bot/test_generate_claude_commands.py::TestRenderCommand::test_injects_summary_format
PASSED tests/bot/test_generate_claude_commands.py::TestRenderCommand::test_injects_snake_rule
PASSED tests/bot/test_generate_claude_commands.py::TestRenderCommand::test_no_unresolved_placeholders
PASSED tests/bot/test_generate_claude_commands.py::TestGenerate::test_generates_all_five_commands
PASSED tests/bot/test_generate_claude_commands.py::TestGenerate::test_output_files_contain_summary_format
PASSED tests/bot/test_generate_claude_commands.py::TestGenerate::test_idempotent
PASSED tests/bot/test_generate_claude_commands.py::TestGenerate::test_creates_output_dir
PASSED tests/bot/test_generate_claude_commands.py::TestGenerate::test_missing_lifecycle_doc_exits
PASSED tests/bot/test_generate_claude_commands.py::TestBuildClaudeMdBlock::test_contains_markers
PASSED tests/bot/test_generate_claude_commands.py::TestBuildClaudeMdBlock::test_contains_overview
PASSED tests/bot/test_generate_claude_commands.py::TestBuildClaudeMdBlock::test_contains_workflow
PASSED tests/bot/test_generate_claude_commands.py::TestMergeClaudeMd::test_creates_file_if_missing
PASSED tests/bot/test_generate_claude_commands.py::TestMergeClaudeMd::test_appends_to_existing_file
PASSED tests/bot/test_generate_claude_commands.py::TestMergeClaudeMd::test_replaces_existing_block
PASSED tests/bot/test_generate_claude_commands.py::TestMergeClaudeMd::test_preserves_content_outside_block
19 passed
```

- [ ] **Step 6: Commit**

```bash
git add tests/bot/test_generate_claude_commands.py
git commit -m "test: add tests for Claude command generator"
```

---

## Task 4: Write `setup-claude-pc.sh`

**Files:**
- Create: `setup-claude-pc.sh`

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# setup-claude-pc.sh
# Installs Claude CLI slash commands and global CLAUDE.md for the feature lifecycle workflow.
# Run this on any PC running the bot, or after changes to docs/feature-lifecycle.md.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Claude PC Feature Lifecycle Setup ==="
echo ""

# ── Check Claude CLI ──────────────────────────────────────────────────────────
if command -v claude &>/dev/null; then
    CLAUDE_VERSION="$(claude --version 2>/dev/null || echo 'unknown')"
    echo "Claude CLI: $CLAUDE_VERSION"
else
    echo "WARNING: Claude CLI not found in PATH."
    echo "  Install from: https://docs.anthropic.com/claude-code"
    echo "  Commands will still be generated, but won't work until Claude CLI is installed."
    echo ""
fi

# ── Check Python ──────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
    echo "ERROR: Python 3 is required but not found in PATH."
    exit 1
fi
PYTHON="$(command -v python3 || command -v python)"

# ── Activate venv if present ──────────────────────────────────────────────────
if [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

# ── Run generator ─────────────────────────────────────────────────────────────
LIFECYCLE_DOC="$SCRIPT_DIR/docs/feature-lifecycle.md"
COMMANDS_DIR="$HOME/.claude/commands"
CLAUDE_MD="$HOME/.claude/CLAUDE.md"

echo "Generating command files from: $LIFECYCLE_DOC"
echo "Installing to: $COMMANDS_DIR"
echo ""

"$PYTHON" "$SCRIPT_DIR/scripts/generate_claude_commands.py" \
    --output-dir "$COMMANDS_DIR" \
    --lifecycle-doc "$LIFECYCLE_DOC" \
    --claude-md "$CLAUDE_MD"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Available slash commands in Claude CLI:"
echo "  /start-feature <name>   Start a new feature (auto-completes any active)"
echo "  /complete-feature       Complete the active feature (writes summary)"
echo "  /resume-feature         Resume a previous feature"
echo "  /list-features          List all features for the current project"
echo "  /discard-feature        Remove a feature from tracking"
echo ""
echo "To update after lifecycle changes: ./setup-claude-pc.sh"
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x setup-claude-pc.sh
```

- [ ] **Step 3: Run it and verify output**

```bash
./setup-claude-pc.sh
```

Expected output:
```
=== Claude PC Feature Lifecycle Setup ===

Claude CLI: ...
Lifecycle doc: .../docs/feature-lifecycle.md
Output dir:    C:\Users\...\..claude\commands

Generated 5 command files:
  ...start-feature.md
  ...complete-feature.md
  ...resume-feature.md
  ...list-features.md
  ...discard-feature.md

Merged feature-lifecycle block into: C:\Users\...\..claude\CLAUDE.md

Done.

=== Setup Complete ===
...
```

- [ ] **Step 4: Verify files exist**

```bash
ls ~/.claude/commands/
```

Expected: 5 `.md` files present.

```bash
grep -c "feature-lifecycle" ~/.claude/CLAUDE.md
```

Expected: a non-zero count (markers present).

- [ ] **Step 5: Commit**

```bash
git add setup-claude-pc.sh
git commit -m "feat: add setup-claude-pc.sh for one-command PC setup"
```

---

## Task 5: Run full test suite and verify no regressions

- [ ] **Step 1: Run all bot tests**

```bash
cd M:/bridgecrew
source venv/Scripts/activate
pytest tests/bot/ -v
```

Expected: all existing tests pass, plus 19 new generator tests.

- [ ] **Step 2: Verify generated command files are well-formed**

Check that the 5 generated command files contain no unresolved `{...}` placeholders:

```bash
grep -l '{[A-Z_]*}' ~/.claude/commands/*.md || echo "No unresolved placeholders found"
```

Expected: `No unresolved placeholders found`

- [ ] **Step 3: Smoke-test a generated command**

Open a project directory and run:
```
/list-features
```

Expected: Claude reads `.claude/features.json` and `.claude/features/*.json` from `$PWD` and displays the feature list.

- [ ] **Step 4: Final commit if any fixes were needed**

```bash
git add -p
git commit -m "fix: address test suite issues from generator integration"
```

---

## Self-Review Notes

**Spec coverage check:**
- `docs/feature-lifecycle.md` — Task 1 ✓
- `scripts/generate_claude_commands.py` — Task 2 ✓
- `setup-claude-pc.sh` — Task 4 ✓
- Tests — Task 3 ✓
- 5 commands (start, complete, resume, list, discard) — embedded in Task 2 templates ✓
- CLAUDE.md merge — `merge_claude_md()` in Task 2, called by setup script in Task 4 ✓
- Idempotency — tested in Task 3, enforced by generator design ✓
- New PC flow — documented in Task 4 step 3 ✓

**No bot code changes** — confirmed by spec; state already lives in `<project>/.claude/features/`.
