# feature-stuff-on-pc

**Started:** 2026-04-05  
**Completed:** 2026-04-15  
**Cost:** $24.0033

## Summary

Completed two major workstreams:

## 1. Feature MCP Migration & CLI Slash Commands
- Migrated Discord bot's feature tracking to the feature-mcp MCP server for session-based consistency across CLI and Discord
- Added feature_abandon_sessions MCP tool, REST endpoint, and Discord /abandon-feature-sessions slash command to clear stale session locks without requiring force=True

## 2. Feature Dashboard Enrichment (composite key + markdown + per-model costs)
- Replaced ULID-based feature_id with a deterministic composite key (project_name:feature_name) so the same identifier works across feature-mcp and the dashboard — no UUID mapping needed
- Wired up dead feature registration pipeline: features now sync to MongoDB when started and completed via the Discord bot
- Added markdown_content field populated from the feature .md file on disk when a feature completes
- Added per-model cost breakdown API endpoint (GET /features/{feature_id}/costs/breakdown) aggregating from cost_log collection
- Fixed cost attribution in _run_stream to use the composite key instead of always-empty bridgecrew_feature_id
- Frontend: per-model cost breakdown on each feature card, collapsible markdown panel for completed features (LCARS-styled)
- Added DB indexes for features.feature_id (unique) and cost_log.feature_id for query performance
- DuplicateKeyError handling for idempotent feature registration on bot restart
