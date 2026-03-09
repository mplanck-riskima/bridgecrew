# Discord Claude Bot - Implementation Plan

## Context

Build a Discord bot in Python that wraps the `claude` CLI. The bot runs from a **workspace root directory** where every subdirectory is a project (each with its own git repo). Projects are auto-discovered — no manual registration. The bot operates in a **single Discord channel** and creates **threads** for project interactions. Claude subprocesses are scoped to the project's directory so Claude only sees that project's files (no context bloat). The bot manages multiple features per project, each with its own Claude session.

---

## Workspace Layout

```
M:/projects/                      # ← WORKSPACE_DIR (configured in .env)
├── myapp/                        # Project — has its own git repo
│   ├── .git/
│   ├── .claude-bot/              # Bot state for this project
│   │   └── state.json
│   └── src/...
├── api-service/                  # Another project
│   ├── .git/
│   ├── .claude-bot/
│   └── ...
└── frontend/                     # Another project
    ├── .git/
    ├── .claude-bot/
    └── ...
```

The bot itself lives separately at `M:/discord-claude/` and points to the workspace via `WORKSPACE_DIR` in `.env`.

---

## Bot Project Structure

```
M:/discord-claude/
├── .env                          # Discord token, guild ID, CHANNEL_ID, WORKSPACE_DIR
├── .gitignore
├── requirements.txt              # discord.py, python-dotenv
├── config.json                   # Bot-level config (thread mappings cache)
├── bot.py                        # Entry point
├── cogs/
│   ├── __init__.py
│   ├── projects.py               # /projects, /sync-projects (auto-discovery)
│   ├── features.py               # /start-feature, /switch-feature, /list-features
│   ├── claude_prompt.py          # @mention handler + prompt relay
│   └── status.py                 # /status command
├── core/
│   ├── __init__.py
│   ├── claude_runner.py          # Subprocess spawning, stream-json parsing, session mgmt
│   ├── discord_streamer.py       # Edit-in-place streaming with rate limiting
│   ├── project_manager.py        # Auto-discovery, thread creation, workspace scanning
│   ├── feature_manager.py        # Feature lifecycle within projects
│   └── state.py                  # State read/write for .claude-bot/ and config.json
└── models/
    ├── __init__.py
    ├── project.py                # Project dataclass
    ├── feature.py                # Feature dataclass
    └── session.py                # Session/stream event dataclasses
```

---

## Core Modules

### `bot.py` — Entry Point
- Load `.env` (Discord token, guild ID, **CHANNEL_ID**, **WORKSPACE_DIR**)
- Init `commands.Bot` with message content + guilds intents
- **On ready**: scan `WORKSPACE_DIR` for subdirectories, auto-create threads for any new projects
- Register all cogs
- Graceful shutdown: kill running claude subprocesses, flush state

### `core/project_manager.py` — Project Auto-Discovery
- **`scan_workspace()`**: List immediate subdirectories of `WORKSPACE_DIR`; each subdir = a project
- Optionally filter to only dirs containing `.git/` (configurable)
- On scan: compare discovered projects against `config.json` thread mappings
  - New project found → create thread named `project: {name}` in the bot channel, init `.claude-bot/state.json`, add to config
  - Project dir deleted → optionally archive the thread
- **`/sync-projects`** slash command triggers a manual re-scan
- Auto-scan on bot startup
- Bidirectional mapping: thread_id <-> project name <-> workspace subdir path

**Critical**: The project directory path is always `WORKSPACE_DIR / project_name`. No arbitrary paths — this ensures Claude subprocess `cwd` is always scoped correctly and can't escape.

### `core/claude_runner.py` — Claude CLI Integration (most critical)
- Spawn `claude` via `asyncio.create_subprocess_exec`
- **Must remove `CLAUDECODE` env var** — CLI refuses to launch if set
- Flags: `-p`, `--output-format stream-json`, `--session-id <uuid>`, `--dangerously-skip-permissions`
- **`cwd` = `WORKSPACE_DIR / project_name`** — scopes Claude to only that project's files
- Parse newline-delimited JSON, yield `StreamEvent` objects via async generator
- Track one active subprocess per project thread
- Support cancellation (kill process on user command)

```python
async def run_claude(prompt, project_dir, session_id=None, resume=False) -> AsyncGenerator[StreamEvent, None]
```

The `cwd` scoping is the key design decision: Claude CLI reads the directory it's launched from to build context. By setting `cwd` to the specific project subdir, Claude only sees that project's files — not sibling projects or the workspace root.

### `core/discord_streamer.py` — Edit-in-Place Streaming
- Buffer text chunks, throttle edits to ~300ms intervals
- Track accumulated length; when >1900 chars, finalize message, start new one
- Handle code block splitting (close/reopen ``` across message boundaries)
- Show "Thinking..." while waiting for first output

### `core/feature_manager.py` — Feature Management
- Start feature: generate UUID session_id, set as active, pause previous (name only, no description)
- Switch feature: pause current, activate target
- Each feature's session_id used with `--session-id` / `--resume` for Claude continuity

### `core/state.py` — State Persistence
- Atomic writes (write to temp, rename)
- Two levels of state:

**Bot-level** (`M:/discord-claude/config.json`):
```json
{
  "guild_id": 123456,
  "channel_id": 999888777,
  "workspace_dir": "M:/projects",
  "projects": {
    "myapp": {
      "thread_id": 111222333
    },
    "api-service": {
      "thread_id": 444555666
    }
  }
}
```

No `directory` field needed — path is always `workspace_dir / project_name`.

**Project-level** (`WORKSPACE_DIR/myapp/.claude-bot/state.json`):
```json
{
  "current_feature": "auth-system",
  "features": {
    "auth-system": {
      "session_id": "uuid-here",
      "started_at": "2026-03-08T12:00:00Z",
      "status": "active"
    }
  },
  "history": [
    { "timestamp": "...", "user": "MaxPlanck", "prompt_summary": "Add login endpoint", "feature": "auth-system" }
  ]
}
```

---

## Thread Model

The bot operates in **one channel** (configured via `CHANNEL_ID` in `.env`):

- **Main channel**: Used for slash commands like `/projects`, `/sync-projects`, `/status`
- **Project threads**: Each project gets a thread (e.g., `project: myapp`). Users send prompts and manage features within the thread.
- Thread creation: `channel.create_thread(name=f"project: {name}", type=discord.ChannelType.public_thread)`
- Threads are auto-archived by Discord after inactivity; the bot unarchives them when needed

When a user sends a message in a thread, the bot resolves thread_id → project and scopes the Claude subprocess accordingly.

---

## Interaction Flows

### Project Discovery (automatic)
```
Bot starts up / user runs /sync-projects (in main channel)
  → Scan WORKSPACE_DIR for subdirectories
  → For each subdir not yet in config.json:
      → Create thread "project: {dirname}" in the bot channel
      → Create {subdir}/.claude-bot/state.json
      → Add thread mapping to config.json
  → For any config entry whose subdir no longer exists:
      → Log warning, optionally archive thread
  → Report in main channel: "Found 3 projects: myapp, api-service, frontend. Created 1 new thread."
```

### Send Prompt (@mention in thread)
```
@ClaudeBot add a health check endpoint      (in thread "project: myapp")
  → Resolve thread → project name "myapp"
  → project_dir = WORKSPACE_DIR / "myapp"
  → Get current feature + session_id from project_dir/.claude-bot/state.json
  → Reject if claude already running for this project (or queue)
  → Send "Thinking..." message in the thread
  → Spawn: claude -p --output-format stream-json --session-id <uuid> --dangerously-skip-permissions "prompt"
       cwd = M:/projects/myapp     ← Claude only sees myapp's files
       env = os.environ minus CLAUDECODE
  → Stream chunks → discord_streamer.feed() (messages posted in the thread)
  → On done → discord_streamer.finalize(), save session state, log to history
```

### Feature Management (within a project thread)
```
/start-feature name:auth-system           (in thread "project: myapp")
  → Generate new UUID session_id
  → Pause previously active feature
  → Set new feature as active in .claude-bot/state.json
  → "Feature 'auth-system' started with fresh Claude session."

/switch-feature name:api-endpoints
  → Pause current, activate target
  → Next prompt uses that feature's session_id with --resume

/status
  → Current project (from thread), active feature, running state, last prompt, cost
```

### List Projects (main channel)
```
/projects
  → Read config.json, list all projects with their threads and active features
```

---

## Implementation Order

| Phase | What | Files |
|-------|------|-------|
| 1 | Bot skeleton + Claude subprocess streaming | `bot.py`, `core/claude_runner.py`, `core/discord_streamer.py` |
| 2 | Workspace scanning + thread auto-creation | `core/project_manager.py`, `core/state.py`, `cogs/projects.py`, models |
| 3 | @mention prompt relay (end-to-end) | `cogs/claude_prompt.py` |
| 4 | Feature management + status | `core/feature_manager.py`, `cogs/features.py`, `cogs/status.py` |
| 5 | Polish: error handling, concurrency guards, graceful shutdown | All files |

---

## Edge Cases & Error Handling

- **CLAUDECODE env var**: Must be removed from subprocess env or CLI refuses to start
- **cwd scoping**: Always `WORKSPACE_DIR / project_name` — never workspace root, never arbitrary paths
- **New project added to workspace**: Detected on `/sync-projects` or bot restart; thread auto-created
- **Project dir deleted**: Detected on scan; warn in Discord, skip thread creation
- **Thread auto-archived**: Discord auto-archives inactive threads; bot unarchives on next interaction or scan
- **2000 char limit**: Streamer splits messages, handles open code blocks across splits
- **Rate limits**: 300ms throttle on edits; discord.py handles 429s internally
- **Concurrent prompts**: One active claude process per project; queue or reject extras
- **Subprocess crash/timeout**: Catch errors, notify thread, clean up state; 10min default timeout
- **Invalid session**: Fall back to fresh session if --resume fails
- **Thread deleted manually**: Detect on next scan, re-create
- **State corruption**: Atomic writes (temp file + rename)
- **Graceful shutdown**: SIGTERM running subprocesses, wait 5s, SIGKILL remaining, flush state
- **Subdirs that aren't projects**: Optionally filter by `.git/` presence; ignore hidden dirs (`.`, `_`)
- **Message in main channel (not a thread)**: Only respond to slash commands; ignore @mentions outside threads

---

## Verification

1. Start the bot: `python bot.py` — confirm it connects and scans workspace
2. Add a new directory to workspace — run `/sync-projects` — confirm thread auto-created + `.claude-bot/` initialized
3. In the "project: myapp" thread, `@ClaudeBot hello` — confirm streaming response edits in place
4. Verify Claude's `cwd` is the project dir (ask Claude "what directory are you in?")
5. `/start-feature name:foo` in thread — confirm session isolation
6. `/switch-feature` back and forth — confirm sessions preserved
7. `/status` — confirm it shows current state
8. Send a long prompt producing >2000 chars — confirm message splitting
9. Send a prompt while one is running — confirm queuing/rejection
10. `/projects` in main channel — confirm all workspace subdirs listed with thread links
