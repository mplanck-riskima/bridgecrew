#!/usr/bin/env python3
"""
Generate Claude CLI slash command files and update ~/.claude/CLAUDE.md for the
feature-mcp workflow.

Usage:
    python scripts/generate_claude_commands.py [--output-dir DIR] [--claude-md PATH]

Defaults:
    --output-dir  ~/.claude/commands
    --claude-md   ~/.claude/CLAUDE.md
"""
import argparse
import json
import re
from pathlib import Path


# ── Command templates ─────────────────────────────────────────────────────────

_START_FEATURE = """\
Start a new feature for the current project.

**Feature name:** $ARGUMENTS

Call `feature_start` with:
- `project_dir`: the current working directory
- `session_id`: your session ID
- `name`: $ARGUMENTS

If the result is `status: "conflict"`, show the `warning` and `recommendation`
fields to the user verbatim, then ask if they want to force-take the feature.
Only call again with `force=True` if they confirm.
"""

_COMPLETE_FEATURE = """\
Complete the currently active feature for the project in the current working directory.

Call `feature_complete` with:
- `project_dir`: the current working directory
- `session_id`: your session ID
- `summary`: a 200-400 word summary covering what the feature set out to do,
  what was actually built, key technical decisions and why, any known gaps or
  follow-up work, and notable files changed.
"""

_RESUME_FEATURE = """\
Resume a feature for the project in the current working directory.

1. Call `feature_list` with `project_dir` = current working directory to show
   the user the available features.
2. Ask the user which feature to resume.
3. Call `feature_resume` with:
   - `project_dir`: the current working directory
   - `session_id`: your session ID
   - `feature_name`: the chosen feature name

If the result is `status: "conflict"`, show the `warning` and `recommendation`
fields to the user verbatim, then ask if they want to force-take the feature.
Only call again with `force=True` if they confirm.
"""

_LIST_FEATURES = """\
List all features for the project in the current working directory.

Call `feature_list` with `project_dir` = current working directory and display
the results in a readable table showing name, status, started date, and
milestone count.
"""

_DISCARD_FEATURE = """\
Discard a feature from the project in the current working directory.
This removes its tracking record and archives its summary doc.

1. Call `feature_list` with `project_dir` = current working directory to show
   available features.
2. Ask the user which feature to discard and confirm before proceeding.
3. Call `feature_discard` with:
   - `project_dir`: the current working directory
   - `session_id`: your session ID
"""

COMMANDS: dict[str, str] = {
    "start-feature": _START_FEATURE,
    "complete-feature": _COMPLETE_FEATURE,
    "resume-feature": _RESUME_FEATURE,
    "list-features": _LIST_FEATURES,
    "discard-feature": _DISCARD_FEATURE,
}


def generate(output_dir: Path) -> list[str]:
    """Write command .md files. Returns list of written paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in COMMANDS.items():
        out_path = output_dir / f"{name}.md"
        out_path.write_text(content, encoding="utf-8")
        written.append(str(out_path))
    return written


_CLAUDE_MD_BLOCK = """\
# BEGIN: feature-mcp
# Do not edit this block manually — re-run setup-claude-pc.sh to update.

## Feature Lifecycle

Feature state is managed by the **feature-mcp** MCP server running on `localhost:8765`.

**At the start of every session**, call:
```
feature_context(project_dir="<absolute path>", session_id="<your session id>")
```
This returns your active feature (if any) and a list of all project features.

**Available tools:**
- `feature_context(project_dir, session_id)` — get active feature + feature list (call at session start)
- `feature_start(project_dir, session_id, name, description?, force?)` — start a new feature
- `feature_resume(project_dir, session_id, feature_name, force?)` — resume an existing feature
- `feature_complete(project_dir, session_id, summary)` — complete and write summary
- `feature_add_milestone(project_dir, session_id, text)` — record a mid-session milestone
- `feature_list(project_dir)` — list all features
- `feature_discard(project_dir, session_id)` — discard and archive

**Conflict handling:** If `feature_resume` or `feature_start` returns `status: "conflict"`,
show the warning and recommendation to the user verbatim before calling again with `force=True`.

# END: feature-mcp"""


def merge_claude_md(claude_md_path: Path, block: str) -> None:
    """Replace the feature-lifecycle or feature-mcp block in ~/.claude/CLAUDE.md."""
    # Match either the old or new block markers
    pattern = re.compile(
        r"# BEGIN: feature-(?:lifecycle|mcp).*?# END: feature-(?:lifecycle|mcp)",
        re.DOTALL,
    )

    if claude_md_path.exists():
        existing = claude_md_path.read_text(encoding="utf-8")
        if pattern.search(existing):
            new_content = pattern.sub(block, existing)
        else:
            new_content = existing.rstrip("\n") + "\n\n" + block + "\n"
    else:
        claude_md_path.parent.mkdir(parents=True, exist_ok=True)
        new_content = block + "\n"

    claude_md_path.write_text(new_content, encoding="utf-8")


def merge_mcp_json(mcp_json_path: Path) -> None:
    """Add feature-mcp entry to ~/.claude/.mcp.json, creating if needed."""
    entry = {
        "type": "sse",
        "url": "http://localhost:8765/mcp",
    }
    if mcp_json_path.exists():
        try:
            data = json.loads(mcp_json_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        mcp_json_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}

    data["feature-mcp"] = entry
    mcp_json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.home() / ".claude" / "commands",
        help="Directory to write command .md files (default: ~/.claude/commands)",
    )
    parser.add_argument(
        "--claude-md",
        type=Path,
        default=Path.home() / ".claude" / "CLAUDE.md",
        help="Path to user-level CLAUDE.md (default: ~/.claude/CLAUDE.md)",
    )
    parser.add_argument(
        "--mcp-json",
        type=Path,
        default=Path.home() / ".claude" / ".mcp.json",
        help="Path to ~/.claude/.mcp.json (default: ~/.claude/.mcp.json)",
    )
    parser.add_argument("--skip-claude-md", action="store_true")
    parser.add_argument("--skip-mcp-json", action="store_true")
    args = parser.parse_args()

    print(f"Output dir: {args.output_dir}")
    written = generate(args.output_dir)
    print(f"\nGenerated {len(written)} command files:")
    for path in written:
        print(f"  {path}")

    if not args.skip_claude_md:
        merge_claude_md(args.claude_md, _CLAUDE_MD_BLOCK)
        print(f"\nMerged feature-mcp block into: {args.claude_md}")

    if not args.skip_mcp_json:
        merge_mcp_json(args.mcp_json)
        print(f"Registered feature-mcp in: {args.mcp_json}")

    print("\nDone.")


if __name__ == "__main__":
    main()
