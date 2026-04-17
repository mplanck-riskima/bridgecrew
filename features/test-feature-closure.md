# test-feature-closure

**Started:** 2026-04-13  
**Completed:** 2026-04-16  
**Cost:** $0.0000

## Summary

Added `feature_abandon_sessions` to the feature-mcp system to solve stale session conflict locks that prevented resuming features after a Claude CLI session died without cleanly releasing its lock. Key additions: (1) `_abandon_all_sessions()` helper in `feature-mcp/mcp_tools.py` that clears in-memory and stale JSON session entries, resets `session_id` to None, and returns abandoned count — leaving feature status as "active" so it's immediately resumable; (2) `feature_abandon_sessions` MCP tool as a thin wrapper for Claude CLI use; (3) `POST /api/projects/{path}/features/{feature_name}/abandon-sessions` REST endpoint in `feature-mcp/rest_api.py`; (4) `abandon_feature_sessions()` async HTTP client in `core/mcp_client.py` returning `int | None` so the Discord UI can surface the count; (5) `/abandon-feature-sessions` Discord slash command in `discord_cogs/features.py` with dropdown filtered to features with active sessions, confirmation step, and result message. Also fixed reset-context feature session conflict bug (discord_cogs/claude_prompt.py calls complete_feature on old session before resuming new one) and stale project cleanup in core/project_manager.py. Design: `FeatureStore.get_all_sessions_for_feature()` added as a public method to keep encapsulation clean. CLAUDE.md tools list and `scripts/generate_claude_commands.py` updated. 75 tests passing.

## Milestones

- **2026-04-14 23:17** — Session continuity test: Verified that feature state persists correctly across multiple sessions. This session (session-bridgecrew-new) successfully resumed the test-feature-closure feature after two prior sessions (discord-bot-test-1776119302 via REST, session-bridgecrew-2026-04-14 via CLI) had completed. Confirmed that feature_context returns consistent session ID and feature state within a session. No code changes made — this is a pure lifecycle/continuity verification feature. Background: the feature-mcp server was recently embedded into the repo (commit b73d2cb) and the feature-stuff-on-pc feature was completed, bringing CLI-based feature tracking to parity with the Discord bot. No pending follow-ups for this test feature.
- **2026-04-14 23:23** — Fixed reset-context feature session conflict bug. Two changes made:

1. **discord_cogs/claude_prompt.py** — In `run_feature_context_reset_session`, added a direct `complete_feature` call (via `core.mcp_client`) on the old session between Step 1 (milestone snapshot) and Step 2 (fresh session resume). This releases the old session's lock on the feature before the new session tries to `feature_resume`, preventing the conflict error that was occurring.

2. **core/project_manager.py** — In the project sync/discovery loop, changed the "directory missing" handling from a no-op label to actually removing the project from tracking: pops from `_projects`, removes from `_thread_to_project` map, removes from config, and saves config. Previously stale projects were flagged but never cleaned up.

Pending: verify the reset-context flow end-to-end after bot restart to confirm the fix works.
- **2026-04-15 04:28** — Completed the full abandon-feature-sessions implementation and verified the lifecycle end-to-end.

**What was built (9 commits, c085dd0–5d8b96b):**

1. `_abandon_all_sessions(store, project_dir, feature_name) -> int` helper in `feature-mcp/mcp_tools.py` — clears both in-memory session registry and stale JSON active-session entries, nulls `data["session_id"]`, leaves feature `status` unchanged.
2. `get_all_sessions_for_feature()` public method added to `FeatureStore` in `feature-mcp/feature_store.py` — avoids direct `_sessions` dict access from outside the class.
3. `feature_abandon_sessions(project_dir, feature_name)` MCP tool in `feature-mcp/mcp_tools.py`.
4. `POST /api/projects/{path}/features/{feature_name}/abandon-sessions` REST endpoint in `feature-mcp/rest_api.py`.
5. `abandon_feature_sessions(project_dir, feature_name) -> int | None` async function in `core/mcp_client.py` — returns count on success, None on failure.
6. `/abandon-feature-sessions` Discord slash command in `discord_cogs/features.py` with `AbandonSessionsSelect`, `AbandonSessionsSelectView`, `AbandonSessionsConfirmView` UI classes. Dropdown filtered to features with active sessions only; success message shows "Abandoned N session(s)".
7. `scripts/generate_claude_commands.py` updated — `_CLAUDE_MD_BLOCK` now lists `feature_abandon_sessions` and documents it as an alternative to `force=True` in conflict handling. `setup-claude-pc.sh` was re-run to apply changes to `~/.claude/CLAUDE.md`.

**Tests:** 75 passing in `feature-mcp/tests/` (6 new tool tests, 3 new REST tests).

**Design decisions:**
- `mcp_client` returns `int | None` (not `bool`) so the Discord UI can surface the abandoned count.
- Feature `status` intentionally left as `"active"` post-abandon — feature is still ongoing, only the session lock is cleared.
- All callers pre-check feature existence before calling `_abandon_all_sessions`, so the helper has no defensive null branch.

**Lifecycle verified this session:** conflict → abandon → resume cleanly → complete → resume again (no conflict). Feature is currently active and completed.
- **2026-04-15 17:55** — Context reset test checkpoint (2026-04-15). Active feature: test-feature-closure. Current state: feature has 3 prior milestones covering (1) session continuity verification, (2) reset-context conflict bug fix, and (3) full abandon-sessions implementation. Two active sessions exist at checkpoint time: session-2026-04-15-start and test-milestone-session. This milestone is intentionally written to serve as a pre-restart state snapshot — after restarting the MCP server, feature_context should recover this milestone from persistent JSON storage and the session history should reflect that both active sessions were interrupted. No code changes in this session — pure lifecycle/state test.
- **2026-04-15 18:02** — Context reset milestone (2026-04-15, session 3d64e581). No code changes in this session — pure lifecycle/state testing for MCP server restart recovery.

Session activity:
- Called feature_context at session start; confirmed 4 prior milestones and multiple sessions (session-2026-04-15-start and test-milestone-session both still showing active from previous sessions).
- Added pre-restart checkpoint milestone via test-milestone-session to verify persistent JSON survives MCP server restart.
- User asked about a confidence value display in the myvillage-apps portfolio (showing in cents instead of as a decimal score) — this is a pending follow-up in the myvillage-apps project, unrelated to this feature.
- This session resumed with force=True due to stale session-2026-04-15-start lock still being active.

No pending follow-ups for this feature. Feature remains active for further lifecycle testing.
