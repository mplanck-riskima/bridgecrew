# feature-stuff-on-pc

**Started:** 2026-04-05  
**Completed:** 2026-04-13  
**Cost:** $24.0033

## Summary

CLI slash commands and setup script that bring the bot's feature lifecycle workflow to Claude CLI on any PC, with the bot repo as the single source of truth. The feature expanded mid-session to also migrate the Discord bot itself from the old `feature_manager.py` to the `feature-mcp` MCP server — making session-based feature tracking consistent across both CLI and bot contexts.

### CLI / PC setup

A canonical lifecycle rules doc (`docs/feature-lifecycle.md`) serves as the single source of truth. A pure-Python generator script (`scripts/generate_claude_commands.py`) reads that doc and renders five Claude slash commands into `~/.claude/commands/`. A setup script (`setup-claude-pc.sh`) runs the generator, installs the commands, merges the lifecycle rules into `~/.claude/CLAUDE.md`, and writes the `enabledMcpjsonServers` entry into `settings.json` to wire the feature-mcp server automatically.

### Bot migration to feature-mcp

- Removed `core/feature_manager.py` and all feature I/O from `core/state.py`
- `core/mcp_client.py`: async httpx wrapper the bot uses to talk to the feature-mcp REST API
- `discord_cogs/features.py`: all lifecycle operations now call `run_feature_init_session` which starts a real Claude CLI session that registers with the MCP server immediately
- `discord_cogs/claude_prompt.py`: added `run_feature_init_session` and `run_feature_complete_session`; fixed ask-user/send-file marker stripping before `finalize()`
- `feature-mcp/rest_api.py`: six new REST lifecycle endpoints (register project, start, resume, complete, discard, milestone) + 15 new integration tests
- `feature-mcp/tests/test_e2e_lifecycle.py`: 15 in-process E2E lifecycle tests (FakeMCP + TestClient)
- `tests/e2e/test_feature_mcp.py`: smoke tests against the live server (skip gracefully when server absent)

## Key Files

| File | Purpose |
|---|---|
| `docs/feature-lifecycle.md` | Canonical lifecycle rules — source of truth for generator |
| `scripts/generate_claude_commands.py` | Renders 5 CLI command `.md` files from the lifecycle doc |
| `setup-claude-pc.sh` | One-command setup: generate commands, merge CLAUDE.md, wire MCP server |
| `core/mcp_client.py` | Async httpx wrapper for the feature-mcp REST API |
| `discord_cogs/claude_prompt.py` | `run_feature_init_session`, `run_feature_complete_session` |
| `discord_cogs/features.py` | Discord slash commands driving the feature lifecycle |
| `feature-mcp/rest_api.py` | Six REST lifecycle endpoints |
| `feature-mcp/tests/test_e2e_lifecycle.py` | In-process E2E lifecycle tests |
| `tests/e2e/test_feature_mcp.py` | Live-server smoke tests |

## Design Decisions

- **Session ID as anchor:** The MCP server maps `session_id → feature` so every Claude CLI session always knows which feature it belongs to with no guessing or state-file polling.
- **Bot repo as source of truth:** `setup-claude-pc.sh` regenerates CLI commands from the current bot repo state so lifecycle changes propagate automatically to every PC on next setup run.
- **REST API for the bot, MCP SSE for Claude CLI:** Both sides share the same `FeatureStore`; the bot uses plain HTTP, Claude sessions use MCP tool calls. No duplication of logic.
- **Fallback for stale sessions:** `get_session_feature` falls back to any active feature when the exact session ID doesn't match (handles bot restarts where session ID changes mid-feature).
- **Pure stdlib generator:** No third-party dependencies in the generator; easy to test and portable across machines.
