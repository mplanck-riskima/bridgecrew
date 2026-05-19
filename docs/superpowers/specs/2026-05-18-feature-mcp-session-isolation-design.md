# Feature MCP: Session Isolation Fix

**Date:** 2026-05-18  
**Status:** Approved

## Problem

When a Discord bot session and a Claude CLI session run concurrently on different features, the CLI session loses track of its active feature whenever the bot starts or resumes its own feature.

**Root cause — two bugs working together:**

### Bug 1: `startup()` resurrects stale CLI sessions

`feature_store.py:startup()` rebuilds the in-memory session registry from all active feature JSON files on server start. It registers every session entry marked `status: "active"` — including stale CLI sessions from conversations that have since ended. CLI session IDs are ephemeral (a new UUID per conversation), so restored CLI sessions are always dead. They create phantom in-memory locks that block legitimate new sessions from taking ownership of their features.

REST sessions (the Discord bot) use persistent IDs and may still be live after a restart — restoring those is correct.

### Bug 2: `feature_context` fallback grabs the wrong feature

`mcp_tools.py:feature_context` contains a fallback (lines 29–41) for when a new session has no active feature registered. It iterates all project features, finds the first one with `status == "active"` (alphabetically by filename), auto-attaches the new session to it, and overwrites the JSON's top-level `session_id` pointer.

This fails in multi-session setups: if the bot's feature (e.g., `feature-x.json`) sorts before the CLI's feature (`feature-y.json`), the new CLI session gets attached to the bot's feature. The CLI then "loses" its own feature, and if it calls `feature_start` next, it auto-completes the bot's feature as a side effect.

## Design

Two surgical changes, no data model or protocol changes.

### Fix 1 — `feature_store.py`: Skip CLI sessions during startup recovery

In `startup()`, only register session entries whose `source` is not `"cli"`. CLI sessions are ephemeral; there is no value in restoring them. REST sessions are persistent and should continue to be restored.

```python
# Before
if sess.get("status") == "active":
    self._sessions[sess["session_id"]] = (project_dir, feature_name)

# After
if sess.get("status") == "active" and sess.get("source") != "cli":
    self._sessions[sess["session_id"]] = (project_dir, feature_name)
```

### Fix 2 — `mcp_tools.py`: Make the fallback session-aware

In the `feature_context` fallback, before auto-associating with a candidate feature:

1. Call `get_active_session_for_feature` for that feature.
2. If it returns a non-None session ID — a live session already owns it — skip this feature.
3. Collect all features that pass this check (i.e., active but with no live in-memory session = "orphaned").
4. If exactly one orphaned feature → auto-associate as before.
5. If zero → return `active_feature: null` (no change to existing behavior).
6. If two or more → return `active_feature: null` and include a `resume_candidates` list of feature names so the caller can prompt the user to pick one explicitly.

Do not auto-associate when there is ambiguity. The user must call `feature_resume` explicitly for the multi-candidate case.

## Behavior after fix

| Scenario | Before | After |
|---|---|---|
| Single CLI session, server restart | Auto-associates ✓ | Auto-associates ✓ |
| CLI + bot on different features | CLI grabs bot's feature ✗ | CLI finds its own orphaned feature ✓ |
| Two CLI sessions on different features, server restart | Grabs random one ✗ | Returns `resume_candidates`, user picks ✓ |
| Two CLI sessions on different features, no restart | Grabs random one ✗ | Returns null (both have live sessions) ✓ |

## Files changed

- `feature-mcp/feature_store.py` — `startup()`: add `source != "cli"` filter (~line 113)
- `feature-mcp/mcp_tools.py` — `feature_context` fallback: add live-session check and multi-candidate handling (lines 29–41)

## Out of scope

- No changes to `feature_resume`, `feature_start`, or `feature_complete`
- No data model changes to feature JSON files
- No changes to the REST API or Discord bot
- No heartbeat/keepalive mechanism for session liveness detection
