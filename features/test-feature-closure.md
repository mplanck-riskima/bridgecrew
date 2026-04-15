# test-feature-closure

**Started:** 2026-04-13  
**Completed:** 2026-04-15  
**Cost:** $0.0000

## Summary

Added a dedicated `feature_abandon_sessions` operation to the feature-mcp system, solving the problem of stale session conflict locks that prevented resuming features when a previous Claude CLI session died without cleanly releasing its lock.

**What was built:**

1. `_abandon_all_sessions(store, project_dir, feature_name) -> int` helper in `feature-mcp/mcp_tools.py` — the core operation. It clears both in-memory session registry entries and stale JSON session entries (marked active in the file but not in memory, e.g. after server restart), sets `data["session_id"]` to None, and returns the count abandoned. Feature status is left as "active" so it can be immediately resumed.

2. `feature_abandon_sessions(project_dir, feature_name)` MCP tool registered in the same file — thin wrapper over the helper, for Claude CLI use.

3. `POST /api/projects/{path}/features/{feature_name}/abandon-sessions` REST endpoint in `feature-mcp/rest_api.py` — same operation exposed over HTTP for the Discord bot.

4. `abandon_feature_sessions(project_dir, feature_name) -> int | None` async function in `core/mcp_client.py` — Discord bot's HTTP client for the endpoint. Returns session count on success, None on failure.

5. `/abandon-feature-sessions` Discord slash command in `discord_cogs/features.py` — shows a dropdown filtered to features with active sessions only, confirmation step (with session count in description), and a result message showing "Abandoned N session(s)".

**Key design decisions:**

- `get_all_sessions_for_feature()` was added to `FeatureStore` as a proper public method rather than accessing `_sessions` directly from the helper — keeps encapsulation clean.
- `mcp_client` returns `int | None` rather than `bool` so the Discord UI can surface the actual abandoned count.
- Feature `status` is intentionally left unchanged — the feature is still "active" and immediately resumable; only the session lock is cleared.
- The CLAUDE.md tools list and `scripts/generate_claude_commands.py` were updated to document `feature_abandon_sessions` and note it as an alternative to `force=True` in conflict handling.

**Files changed:** `feature-mcp/mcp_tools.py`, `feature-mcp/feature_store.py`, `feature-mcp/rest_api.py`, `core/mcp_client.py`, `discord_cogs/features.py`, `scripts/generate_claude_commands.py`, plus tests in `feature-mcp/tests/test_tools.py` and `feature-mcp/tests/test_rest_api.py`. 75 tests passing.

## Milestones

- **2026-04-14 23:17** — Session continuity test: Verified that feature state persists correctly across multiple sessions. This session (session-bridgecrew-new) successfully resumed the test-feature-closure feature after two prior sessions (discord-bot-test-1776119302 via REST, session-bridgecrew-2026-04-14 via CLI) had completed. Confirmed that feature_context returns consistent session ID and feature state within a session. No code changes made — this is a pure lifecycle/continuity verification feature. Background: the feature-mcp server was recently embedded into the repo (commit b73d2cb) and the feature-stuff-on-pc feature was completed, bringing CLI-based feature tracking to parity with the Discord bot. No pending follow-ups for this test feature.
- **2026-04-14 23:23** — Fixed reset-context feature session conflict bug. Two changes made:

1. **discord_cogs/claude_prompt.py** — In `run_feature_context_reset_session`, added a direct `complete_feature` call (via `core.mcp_client`) on the old session between Step 1 (milestone snapshot) and Step 2 (fresh session resume). This releases the old session's lock on the feature before the new session tries to `feature_resume`, preventing the conflict error that was occurring.

2. **core/project_manager.py** — In the project sync/discovery loop, changed the "directory missing" handling from a no-op label to actually removing the project from tracking: pops from `_projects`, removes from `_thread_to_project` map, removes from config, and saves config. Previously stale projects were flagged but never cleaned up.

Pending: verify the reset-context flow end-to-end after bot restart to confirm the fix works.
