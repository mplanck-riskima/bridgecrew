# Abandon Feature Sessions — Design

**Date:** 2026-04-14  
**Status:** Approved

## Problem

When resuming a feature via `feature_resume` or `feature_start`, the MCP server returns a `status: "conflict"` error if the feature is currently locked to another session in the in-memory registry. This happens when a previous Claude CLI session terminated without cleanly releasing the lock (e.g. process killed, PC restart, stale session). There is currently no way to clear this lock without force-resuming through another active session.

## Goal

Provide a dedicated operation — exposed as both an MCP tool and a Discord slash command — to abandon all active sessions for a named feature, releasing the conflict lock so the feature can be resumed cleanly.

---

## Architecture

### 1. Shared Helper: `_abandon_all_sessions` (`feature-mcp/mcp_tools.py`)

A module-level function that contains the core logic:

- Scans the in-memory `FeatureStore._sessions` registry for all session IDs associated with `(project_dir, feature_name)` and calls `_abandon_session` on each.
- Also scans the feature JSON's `sessions` list for entries with `status: "active"` that are not in the in-memory registry (stale after server restart) and marks them `abandoned` with `abandoned_at` timestamp.
- Clears `data["session_id"]` (the top-level current-session pointer) on the feature JSON.
- Writes updated feature data.
- Leaves feature `status` unchanged (remains `"active"` so it is immediately resumable without conflict).
- Returns the count of sessions abandoned.

Signature:
```python
def _abandon_all_sessions(store: FeatureStore, project_dir: Path, feature_name: str) -> int:
    ...
```

### 2. MCP Tool: `feature_abandon_sessions` (`feature-mcp/mcp_tools.py`)

```python
@mcp.tool()
def feature_abandon_sessions(project_dir: str, feature_name: str) -> str:
    """Abandon all active sessions for a feature, clearing any conflict lock.
    The feature remains active and can be resumed cleanly afterward."""
```

- Validates `project_dir` via `store.ensure_project_dir`.
- Reads the feature; returns error JSON if not found.
- Calls `_abandon_all_sessions`.
- Returns `{"status": "ok", "feature_name": ..., "abandoned_count": N}`.

### 3. REST Endpoint (`feature-mcp/rest_api.py`)

```
POST /api/projects/{encoded_path}/features/{feature_name}/abandon-sessions
```

- No request body.
- Same validation pattern as other endpoints.
- Calls `_abandon_all_sessions`.
- Returns `{"status": "ok", "feature_name": ..., "abandoned_count": N}`.
- 404 if feature not found.

### 4. MCP Client (`core/mcp_client.py`)

New async function:

```python
async def abandon_feature_sessions(project_dir: Path, feature_name: str) -> bool:
    """Abandon all active sessions for a feature. Returns True on success."""
```

- Posts to `POST /api/projects/{encoded_path}/features/{feature_name}/abandon-sessions`.
- Returns `True` if HTTP 200, `False` otherwise (logs warning on failure).

### 5. Discord Command (`discord_cogs/features.py`)

New slash command: `/abandon-feature-sessions`

**Flow:**
1. Resolves project from thread (same `_resolve_project` pattern).
2. Fetches features via `mcp_client.get_features(project_dir)`.
3. Filters to features that have at least one session entry with `status: "active"` in their JSON.
4. If none found: ephemeral response "No features with active sessions — nothing to abandon."
5. Otherwise: shows `AbandonSessionsSelect` dropdown (one option per qualifying feature, showing name + active session count in description).
6. On selection: shows `AbandonSessionsConfirmView` with:
   - Message: `Abandon all active sessions for **\`{name}\`**? The feature will stay active and be resumable without conflict.`
   - "Abandon" button (danger style)
   - "Cancel" button (secondary style)
7. On confirm: calls `mcp_client.abandon_feature_sessions(project_dir, feature_name)`.
   - Success: `Abandoned N active session(s) for **\`{name}\`**. You can now resume it cleanly.`
   - Failure: `Failed to contact the feature-mcp server. Try again or restart it with \`/restart-server\`.`

**New UI classes (all in `discord_cogs/features.py`):**
- `AbandonSessionsSelect(discord.ui.Select)` — dropdown of features with active sessions
- `AbandonSessionsSelectView(discord.ui.View)` — wraps select
- `AbandonSessionsConfirmView(discord.ui.View)` — confirm/cancel buttons

---

## Data Invariants

- Feature `status` is NOT changed by this operation. An `"active"` feature stays `"active"`.
- Session history is preserved — abandoned sessions appear in `sessions[]` with `status: "abandoned"` and `abandoned_at` timestamp. No data is deleted.
- `data["session_id"]` (top-level current-session pointer) is cleared to `None`.
- After this operation, `get_active_session_for_feature` returns `None`, so subsequent `feature_resume` / `feature_start` calls succeed without conflict.

## What Is NOT Changed

- `_abandon_session` (single-session helper used by force flows) — unchanged.
- All existing slash commands — unchanged.
- Feature milestones, costs, description, history — untouched.

---

## Files Changed

```
feature-mcp/mcp_tools.py     — add _abandon_all_sessions helper + feature_abandon_sessions tool
feature-mcp/rest_api.py      — add POST .../features/{name}/abandon-sessions endpoint
core/mcp_client.py           — add abandon_feature_sessions() async function
discord_cogs/features.py     — add /abandon-feature-sessions command + UI classes
```

---

## Edge Cases

- **Feature not found:** REST and MCP tool both return error; Discord command only shows features that exist (filtered from live feature list).
- **No active sessions:** `_abandon_all_sessions` returns 0; operation is a no-op. Discord command hides these features from the dropdown.
- **MCP server unreachable:** `abandon_feature_sessions()` returns False; Discord command shows failure message.
- **Feature already completed/discarded:** These won't have active sessions, so they won't appear in the dropdown. MCP tool still handles gracefully (returns `abandoned_count: 0`).
