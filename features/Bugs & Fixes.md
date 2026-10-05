# Bugs & Fixes

**Started:** 2026-04-03  
**Completed:** 2026-10-05  
**Cost:** $33.0077

## Summary

Catch-all session covering a range of bug fixes and improvements to the Discord Claude bot and feature-mcp server.

**Feature lifecycle reliability:**
- Fixed `ensure_project_dir` in `feature_store.py` to auto-register unknown projects (previously raised `ValueError`, causing all REST calls to silently 404 for projects not listed in `projects.json`). Projects are now persisted back to `projects.json` on first access.
- `feature-mcp/server.py`: threaded `config_path` through `create_app` so the store can persist newly discovered projects.
- Starting or resuming a feature now suspends all other active features on the same project (`_suspend_feature` / `_suspend_feature_mcp` helpers in `rest_api.py` and `mcp_tools.py`). Introduced `suspended_at` timestamp; cleared on resume. This enforces a single-active-feature workflow and prevents stale `status: active` entries from accumulating.

**`/status` correctness:**
- `discord_cogs/status.py`: active feature is now identified by matching `default_session_id` against session entries before falling back to alphabetical file scan. Fixes the bug where switching features left the old feature name visible in `/status`.

**Bot state consistency:**
- `discord_cogs/claude_prompt.py` (`run_feature_init_session`): after MCP registration, `active_feature_name` in project state is updated and `pending_feature_op` is cleared, so the state always reflects the feature that was just started/resumed.

**Footer — per-window token usage:**
- `core/claude_runner.py`: extended rate_limit_event capture to also collect `tokensLimit` and `tokensRemaining` alongside `resetsAt`, stored as a richer dict per rate-limit type.
- `discord_cogs/claude_prompt.py` footer block: restructured from flat `5h X · week X · 5h ↺ in Xh · 7d ↺ in Xh` to grouped per-window `5h: X/limit (pct%) ↺ Xh · 7d: X/limit (pct%) ↺ Xd`. Reset times show days when >24h. Degrades gracefully when rate-limit events aren't present.

**`/complete-suspended` command:**
- `discord_cogs/features.py`: new slash command that lists all suspended features, lets the user pick one, re-registers its last session with the MCP store via `resume_feature_session`, and fires the existing `run_feature_complete_session` flow so Claude writes the summary and closes out the feature.

**Security:**
- Bot blocks reading or sharing `.env` and credential files (enforced in system prompt and cog logic).

**Key files changed:** `feature-mcp/feature_store.py`, `feature-mcp/rest_api.py`, `feature-mcp/mcp_tools.py`, `feature-mcp/server.py`, `feature-mcp/projects.json`, `discord_cogs/claude_prompt.py`, `discord_cogs/status.py`, `discord_cogs/features.py`, `core/claude_runner.py`.
