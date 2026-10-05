# feature-stuff-on-pc

**Started:** 2026-04-05  
**Completed:** 2026-10-05  
**Cost:** $26.7716

## Summary

Two major workstreams delivered together under this feature.

**1. Feature MCP migration and CLI slash commands**
Migrated the Discord bot's feature lifecycle tracking from an ad-hoc JSON-based system to the feature-mcp MCP server, so feature sessions are consistent whether work happens in Claude CLI on a local PC or via the Discord bot. Key additions:
- `feature_abandon_sessions` MCP tool and matching REST endpoint (`POST /features/{name}/abandon-sessions`) to clear stale session locks without requiring `force=True`
- Discord `/abandon-feature-sessions` slash command exposing the above to users
- `scripts/setup-scheduler.ps1` PC setup script that installs the feature lifecycle workflow (slash commands, MCP config) for Claude CLI on any Windows machine

**2. Feature dashboard enrichment**
- Replaced ULID-based `feature_id` with a deterministic composite key (`project_name:feature_name`) so the same identifier works across feature-mcp, the Discord bot, and MongoDB — no UUID mapping needed
- Bot now registers features in MongoDB when started and completed, writing `markdown_content` from the `.md` summary file on disk
- New `GET /features/{feature_id}/costs/breakdown` API endpoint aggregates per-model cost from the `cost_log` collection
- Fixed cost attribution in `_run_stream` to use the composite key instead of the previously always-empty `bridgecrew_feature_id`
- Frontend: per-model cost breakdown on each feature card, collapsible LCARS-styled markdown panel for completed features, human-readable project URL slugs
- DB indexes added for `features.feature_id` (unique) and `cost_log.feature_id`; `DuplicateKeyError` handled for idempotent re-registration on bot restart
- Migration script to convert existing ULID feature IDs to `project:feature` composite keys

**Key files changed:** `bot.py`, `discord_cogs/claude_prompt.py`, `discord_cogs/status.py`, `dashboard/backend/` (cost breakdown endpoint, feature sync), `dashboard/frontend/` (costs UI, markdown panel), `feature-mcp/` (MCP tools, REST API), `scripts/setup-scheduler.ps1`.
