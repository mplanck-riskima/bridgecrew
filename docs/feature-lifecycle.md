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
