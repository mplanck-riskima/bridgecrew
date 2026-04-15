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
import re
import sys
from pathlib import Path


# ── Command templates ─────────────────────────────────────────────────────────

_START_FEATURE = """\
Start a new feature for the current project.

**Feature name:** $ARGUMENTS

Call `feature_start` with:
- `project_dir`: the current working directory (absolute path)
- `session_id`: your session ID
- `name`: $ARGUMENTS

If the result is `status: "conflict"`, show the `warning` and `recommendation`
fields to the user verbatim, then ask if they want to force-take the feature.
Only call again with `force=True` if they confirm.

On success, confirm: "Feature **`$ARGUMENTS`** started."
If a previously active feature was displaced, mention it by name.

## Summary Format

{SUMMARY_FORMAT}
"""

_COMPLETE_FEATURE = """\
Complete the currently active feature for the project in the current working directory.

Call `feature_complete` with:
- `project_dir`: the current working directory (absolute path)
- `session_id`: your session ID
- `summary`: a 200–400 word summary that covers:
  - What the feature set out to do
  - What was actually built (key components, changes, files)
  - Key technical decisions and the reasoning behind them
  - Any known gaps, limitations, or follow-up work
  - Notable files changed or created

On success, confirm: "Feature **`<name>`** completed. Summary written to `features/<name>.md`."

## Summary Format

{SUMMARY_FORMAT}
"""

_RESUME_FEATURE = """\
Resume a feature for the project in the current working directory.

1. Call `feature_list` with `project_dir` = current working directory.
2. Display the results to the user in a readable list, then ask which feature to resume.
   Wait for their response before continuing.
3. Call `feature_resume` with:
   - `project_dir`: the current working directory (absolute path)
   - `session_id`: your session ID
   - `feature_name`: the chosen feature name

If the result is `status: "conflict"`, show the `warning` and `recommendation`
fields to the user verbatim, then ask if they want to force-take the feature.
Only call again with `force=True` if they confirm.

On success, confirm: "Resumed feature **`<name>`**."

## Summary Format

{SUMMARY_FORMAT}
"""

_LIST_FEATURES = """\
List all features for the project in the current working directory.

Call `feature_list` with `project_dir` = current working directory.

Display results in a monospace block, sorted active-first then by start date
descending, with columns: Name, Status, Started, Milestones. Mark the current
active feature with "<- current". Example format:

```
Features — <project dir basename>
─────────────────────────────────────────────────
Name               Status      Started     Milestones
─────────────────────────────────────────────────
my-feature         active      2026-04-01  3       <- current
old-feature        completed   2026-03-15  7
─────────────────────────────────────────────────
Total: 2  Active: 1
```

If no features exist: "No features yet. Use `/start-feature <name>` to create one."
"""

_DISCARD_FEATURE = """\
Discard a feature from the project in the current working directory.
This removes its tracking record and archives its summary doc.

1. Call `feature_list` with `project_dir` = current working directory to show
   available features. If none exist, tell the user "No features to discard." and stop.
2. Display the list and ask which feature to discard.
3. Ask for confirmation: "Discard **`<name>`**? This cannot be undone. (yes/no)"
   Wait for their response. Only proceed if they confirm.
4. Call `feature_discard` with:
   - `project_dir`: the current working directory (absolute path)
   - `session_id`: your session ID

After discarding, also check `CLAUDE.md` in the project root for a `## Features`
section and remove any bullet line that mentions the discarded feature name.
Only modify the file if such a line exists.

Report what was done: feature discarded, doc archived (if applicable),
CLAUDE.md updated (if applicable).
"""

COMMANDS: dict[str, str] = {
    "start-feature": _START_FEATURE,
    "complete-feature": _COMPLETE_FEATURE,
    "resume-feature": _RESUME_FEATURE,
    "list-features": _LIST_FEATURES,
    "discard-feature": _DISCARD_FEATURE,
}


_SNAKE_RULE = (
    "Feature names are stored in snake_case. "
    "For example: my_feature, add_login, fix_auth_bug. "
    "Always convert names to snake_case when calling feature tools."
)


def extract_section(text: str, section_name: str) -> str:
    """Extract the body of a ## section from markdown text, stopping at the next ## heading."""
    pattern = re.compile(
        r"^## " + re.escape(section_name) + r"\s*\n(.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return ""
    return match.group(1).strip()


def render_command(template: str, summary_format: str) -> str:
    """Replace {SUMMARY_FORMAT} and {SNAKE_RULE} placeholders in a command template."""
    return template.replace("{SUMMARY_FORMAT}", summary_format).replace("{SNAKE_RULE}", _SNAKE_RULE)


def build_claude_md_block(lifecycle_text: str) -> str:
    """Wrap lifecycle doc text in feature-lifecycle CLAUDE.md markers."""
    return "# BEGIN: feature-lifecycle\n" + lifecycle_text.strip() + "\n# END: feature-lifecycle"


def generate(output_dir: Path, lifecycle_path: Path | None = None) -> list[str]:
    """Write command .md files. Returns list of written paths."""
    if lifecycle_path is not None:
        if not lifecycle_path.exists():
            print(f"Error: lifecycle doc not found: {lifecycle_path}", file=sys.stderr)
            raise SystemExit(1)
        lifecycle_text = lifecycle_path.read_text(encoding="utf-8")
        summary_format = extract_section(lifecycle_text, "Summary Format")
    else:
        summary_format = ""

    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, template in COMMANDS.items():
        rendered = render_command(template, summary_format)
        out_path = output_dir / f"{name}.md"
        out_path.write_text(rendered, encoding="utf-8")
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
- `feature_abandon_sessions(project_dir, feature_name)` — abandon all active sessions for a feature, clearing conflict locks

**Conflict handling:** If `feature_resume` or `feature_start` returns `status: "conflict"`,
show the warning and recommendation to the user verbatim before calling again with `force=True`.
Alternatively, call `feature_abandon_sessions(project_dir, feature_name)` to clear the stale lock first,
then resume normally without `force=True`.

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


def register_mcp_server() -> bool:
    """Register feature-mcp via `claude mcp add --scope user`. Returns True on success."""
    import shutil
    import subprocess
    claude_bin = shutil.which("claude")
    if not claude_bin:
        print("WARNING: claude CLI not found — skipping MCP registration.", file=sys.stderr)
        print("  Run manually: claude mcp add --scope user --transport sse feature-mcp http://localhost:8765/mcp/sse", file=sys.stderr)
        return False
    result = subprocess.run(
        [claude_bin, "mcp", "add", "--scope", "user", "--transport", "sse",
         "feature-mcp", "http://localhost:8765/mcp/sse"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # "already exists" isn't an error we care about
        if "already" in (result.stderr + result.stdout).lower():
            return True
        print(f"WARNING: claude mcp add failed: {result.stderr.strip()}", file=sys.stderr)
        return False
    return True


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
        "--lifecycle",
        type=Path,
        default=None,
        help="Path to feature-lifecycle.md to inject Summary Format into commands",
    )
    parser.add_argument("--skip-claude-md", action="store_true")
    parser.add_argument("--skip-mcp", action="store_true")
    args = parser.parse_args()

    print(f"Output dir: {args.output_dir}")
    written = generate(args.output_dir, args.lifecycle)
    print(f"\nGenerated {len(written)} command files:")
    for path in written:
        print(f"  {path}")

    if not args.skip_claude_md:
        merge_claude_md(args.claude_md, _CLAUDE_MD_BLOCK)
        print(f"\nMerged feature-mcp block into: {args.claude_md}")

    if not args.skip_mcp:
        ok = register_mcp_server()
        if ok:
            print("Registered feature-mcp server (user scope) via claude mcp add")

    print("\nDone.")


if __name__ == "__main__":
    main()
