# Feature: Discord Claude Bot

## Summary
A Discord bot in Python that wraps the `claude` CLI as a subprocess. It auto-discovers projects from a workspace directory, creates Discord threads per project, streams Claude's output back via edit-in-place messages, and manages separate features/sessions within each project. Users interact via @mentions for prompts and slash commands for project/feature management.

## Completed
2026-03-09

## Token Usage
- **Total tokens:** ~50,000 (estimated, single session)
- **Sessions:** 1
- **By model:**
  - claude-opus-4-6: ~50,000 tokens
- **Estimated cost:** ~$1.13
  - claude-opus-4-6: ~$1.13 (blended 80/20 input/output at $15/$75 per 1M)

## Key Files

### Entry Point
- `bot.py` — Bot startup, cog registration, workspace auto-scan on ready, graceful shutdown

### Core Modules
- `core/claude_runner.py` — Spawns `claude` subprocess with cwd scoped to project dir, parses stream-json, tracks active processes, supports cancel/kill
- `core/discord_streamer.py` — Edit-in-place streaming with 300ms throttle, 1900-char message splitting, code block continuity, Stop button UI
- `core/project_manager.py` — Workspace scanning, thread auto-creation, project↔thread bidirectional mapping
- `core/feature_manager.py` — Feature lifecycle (start/switch/list), UUID session IDs, history logging
- `core/state.py` — Atomic JSON persistence for bot-level config and project-level `.claude-bot/state.json`

### Cogs (Slash Commands & Handlers)
- `cogs/projects.py` — `/projects`, `/sync-projects`
- `cogs/features.py` — `/start-feature`, `/switch-feature`, `/list-features`
- `cogs/claude_prompt.py` — @mention handler, wires runner + streamer + cancel button
- `cogs/status.py` — `/status`, `/cancel`

### Models
- `models/project.py` — Project dataclass
- `models/feature.py` — Feature dataclass with session tracking
- `models/session.py` — StreamEvent dataclass

### Config
- `.env.example` — Required env vars template
- `requirements.txt` — discord.py, python-dotenv
- `.gitignore`

## Architecture & Design Decisions
- **Workspace-based discovery**: All subdirectories of `WORKSPACE_DIR` are projects — no manual registration needed
- **cwd scoping**: Claude subprocess runs with `cwd` set to the project directory, so it only sees that project's files (prevents context bloat)
- **CLAUDECODE env var removal**: Stripped from subprocess environment to prevent Claude CLI from refusing to launch in nested contexts
- **Edit-in-place streaming**: Single message edited at 300ms intervals; splits at 1900 chars with code block continuity across splits
- **Thread-per-project model**: Bot operates in one channel, each project gets a public thread
- **Session isolation via features**: Each feature gets a UUID session ID used with `--session-id` for Claude conversation continuity
- **Stop button**: Discord UI button (red Stop) attached to streaming messages for immediate process cancellation via `proc.kill()`
- **Atomic state writes**: Temp file + rename pattern to prevent corruption

## How It Works
1. Bot starts, loads `.env`, scans `WORKSPACE_DIR` for subdirectories
2. For each discovered project, creates a Discord thread (`project: {name}`) and initializes `.claude-bot/state.json`
3. Users enter a project thread and @mention the bot with a prompt
4. Bot spawns `claude -p --output-format stream-json --session-id <uuid>` with `cwd` set to the project dir
5. Stream-json output is parsed line-by-line; text deltas are fed to the DiscordStreamer which edits the message in place
6. Users can click the Stop button or use `/cancel` to kill the process mid-stream
7. Features provide session isolation — `/start-feature` creates a new session, `/switch-feature` resumes a prior one

## Known Limitations / Future Work
- No queuing — concurrent prompts to the same project are rejected (could add a queue)
- Thread auto-archive by Discord requires unarchiving on next interaction
- No per-user access control — anyone in the channel can use any project
- No cost tracking aggregation across prompts (stream-json `result` event cost is captured but not persisted/displayed)
- Could add file attachment support for sending files to Claude
- Could add a `/history` command to browse prompt history
