# feature-stuff-on-pc

**Started:** 2026-04-05  
**Completed:** 2026-04-14  
**Cost:** $24.0033

## Summary

CLI slash commands and setup script that bring the bot's feature lifecycle workflow to Claude CLI on any PC, plus migration of the Discord bot's feature tracking from feature_manager.py to the feature-mcp MCP server for session-based consistency. Key components: docs/feature-lifecycle.md (canonical lifecycle rules), scripts/generate_claude_commands.py (renders 5 CLI command .md files), setup-claude-pc.sh (one-command setup), core/mcp_client.py (async httpx wrapper for feature-mcp REST API), discord_cogs/claude_prompt.py (run_feature_init_session, run_feature_complete_session), feature-mcp/rest_api.py (6 new REST lifecycle endpoints), and full E2E + smoke test coverage. Design decisions: session ID as anchor for feature association, bot repo as single source of truth for CLI commands, REST API for bot + MCP SSE for Claude CLI sharing the same FeatureStore, and fallback to any active feature when session ID doesn't match.
