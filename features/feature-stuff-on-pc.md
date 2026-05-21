# feature-stuff-on-pc

**Started:** 2026-04-05  
**Completed:** 2026-05-07  
**Cost:** $26.7716

## Summary

## feature-stuff-on-pc

Two major workstreams completed:

### 1. Feature MCP Migration & CLI Slash Commands
- Migrated Discord bot's feature tracking to the feature-mcp MCP server so feature sessions are consistent across both Claude CLI and Discord
- Added `feature_abandon_sessions` MCP tool, REST endpoint (`POST /features/{name}/abandon-sessions`), and Discord `/abandon-feature-sessions` slash command to clear stale session locks without needing `force=True`
- Setup script brings the feature lifecycle workflow to Claude CLI on any PC, bridging local dev and Discord-based work

### 2. Feature Dashboard Enrichment (composite key + markdown + per-model costs)
- Replaced ULID-based `feature_id` with a deterministic composite key (`project_name:feature_name`) so the same identifier works across feature-mcp and the MongoDB dashboard — no UUID mapping needed
- Wired up feature registration pipeline: features sync to MongoDB when started/completed via the Discord bot
- Added `markdown_content` field populated from the feature `.md` file on disk at completion time
- Added per-model cost breakdown API endpoint (`GET /features/{feature_id}/costs/breakdown`) aggregating from `cost_log` collection
- Fixed cost attribution in `_run_stream` to use the composite key instead of always-empty `bridgecrew_feature_id`
- Frontend: per-model cost breakdown on each feature card, collapsible LCARS-styled markdown panel for completed features
- Added DB indexes for `features.feature_id` (unique) and `cost_log.feature_id` for query performance
- `DuplicateKeyError` handling for idempotent feature registration on bot restart
- Migration script to convert existing ULID feature IDs to `project:feature` composite keys

### Key files changed
- `bot.py` — feature session helpers, composite key attribution
- `discord_cogs/claude_prompt.py` — feature lifecycle hooks, cost attribution fix
- `discord_cogs/status.py` — `/abandon-feature-sessions` slash command
- `dashboard/backend/` — new cost breakdown endpoint, feature sync API
- `dashboard/frontend/` — per-model costs UI, markdown panel, human-readable project URLs
- `.claude/features/feature_stuff_on_pc.json` — feature MCP state file
- `scripts/setup-scheduler.ps1` — PC setup script
