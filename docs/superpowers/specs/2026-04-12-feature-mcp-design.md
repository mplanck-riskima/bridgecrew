# Feature MCP Server — Design Spec

**Date:** 2026-04-12
**Status:** Approved for implementation

## Problem

Feature lifecycle management currently lives in two places that can collide:

1. **Bot Python code** (`core/feature_manager.py`) — manages feature state for Discord sessions
2. **CLAUDE.md prompt block** — tells terminal Claude sessions how to manipulate the same JSON files directly

When a Discord session and a terminal session work on the same project simultaneously, they read and write the same `.claude/features.json` with no coordination. The `current_feature` field is global per project, not per session, so one session's lifecycle operations silently overwrite the other's.

## Solution

A persistent MCP server (`M:\feature-mcp`) running on `localhost:8765` becomes the single source of truth for all feature state. Both Discord bot Claude subprocesses and terminal Claude sessions connect to it via MCP-over-HTTP. The bot's Python code calls its REST API for cost recording and display. The bot drops `core/feature_manager.py` entirely.

---

## Architecture

### Transport: HTTP/SSE (persistent server)

stdio is not viable for shared state — it spawns a fresh process per Claude session with no shared memory. A persistent HTTP server is the single authority that all sessions talk to.

**Two interfaces on the same process:**
- `POST /mcp` (SSE) — MCP transport, consumed by Claude sessions
- `/api/*` — plain REST, consumed by the bot's Python code

### Project structure

```
M:\feature-mcp\
  server.py          # startup: wires MCP + FastAPI, rebuilds in-memory state
  feature_store.py   # all file I/O and in-memory session→feature routing
  mcp_tools.py       # MCP tool definitions, summary prompt text
  rest_api.py        # FastAPI REST routes for the bot
  requirements.txt
```

### State storage

**In-memory (rebuilt on startup):**
```python
sessions: dict[session_id, tuple[project_dir, feature_name]]
```
Populated on startup by scanning all `<project>/.claude/features/*.json` for `status == "active"`.

**Persistent (file-based, git-tracked):**
Same `.claude/features/` directory structure already in place. No schema changes to existing tools that read these files.

### Registration

Registered globally in `~/.claude/claude_desktop_config.json` (and any other MCP config files used by this machine) as an HTTP MCP server at `http://localhost:8765/mcp`. Every Claude session on this machine automatically has access.

---

## Data Model

### `.claude/features/<snake_name>.json`

```json
{
  "name": "my-feature",
  "status": "active",
  "session_id": "<most-recent-session-uuid>",
  "sessions": [
    {
      "session_id": "abc-123",
      "session_start": "2026-04-10T17:00:00+00:00",
      "source": "discord",
      "status": "abandoned"
    },
    {
      "session_id": "def-456",
      "session_start": "2026-04-12T09:00:00+00:00",
      "source": "cli",
      "status": "active"
    }
  ],
  "milestones": [
    {
      "timestamp": "2026-04-12T09:30:00+00:00",
      "session_id": "def-456",
      "text": "Replaced audioop resampling with FFmpeg pipeline"
    }
  ],
  "started_at": "2026-04-10T17:00:00+00:00",
  "completed_at": null,
  "total_cost_usd": 4.20,
  "total_input_tokens": 180000,
  "total_output_tokens": 9000
}
```

**New vs existing fields:**
- `sessions[].status` — new: `active | abandoned | completed`
- `milestones` — new array, empty by default
- All other fields unchanged from current schema

### `.claude/features.json`

```json
{}
```

Both the `current_feature` field and the `sessions` routing map are removed. The MCP owns all session routing in memory. The file is kept as an empty object for backward compatibility (tools that check for its existence won't break), but nothing writes to it.

### `features/<name>.md`

Written by the MCP on `feature_complete`. Same format as today — the MCP generates it from the feature JSON + the summary text Claude provides.

---

## MCP Tools

All tools take `project_dir` (absolute path) and `session_id` (Claude session UUID) unless noted.

### `feature_context(project_dir, session_id)`

Called at the start of every Claude session. Returns:
- Active feature for this session if one exists (name, description, milestones, recent sessions)
- List of all features for the project with status

This replaces the CLAUDE.md feature lifecycle prompt block. Claude gets its bearings by calling this rather than reading static instructions.

**No side effects** — read-only.

### `feature_start(project_dir, session_id, name, description?)`

Starts a new feature and registers the session→feature mapping.

- If this session already has an active feature, auto-completes it first with a placeholder summary (flagged as needing proper completion)
- If `name` matches an already-active feature under a **different** session, triggers the same two-step conflict flow as `feature_resume` — returns `status: "conflict"` on first call, requires `force=True` to take over
- Starting a unique-named feature while a different feature is active under a different session on the same project is allowed — independent workstreams don't block each other

### `feature_resume(project_dir, session_id, feature_name, force?)`

Associates this session with an existing feature.

**Conflict flow (feature is active under another session):**

First call (no `force`): returns `status: "conflict"` with:
- Warning that the feature is live in another session and context may be lost
- The other session's ID and last-active timestamp
- Explicit recommendation: resume that session and complete it there first
- Instructions: pass `force=True` only after presenting this warning to the user and confirming they want to proceed

Second call with `force=True`: marks the old session as `abandoned` in the sessions history (timestamped), assigns this session as active. The abandoned session's record is preserved — nothing is deleted.

**No conflict:** feature exists but has no active session → resumes immediately, no warning.

### `feature_complete(project_dir, session_id, summary)`

Completes the feature and writes the `features/<name>.md` summary file.

The tool description contains rich instructions for what the summary should cover so Claude sees the guidance at the moment it's composing the summary:

> The summary should include: what the feature set out to do, what was actually built, key technical decisions and why they were made, any known gaps or follow-up work, and notable files changed. Aim for 200–400 words — enough for a future Claude session to get full context without reading the git history.

Marks the session's status as `completed`. Removes the session from the in-memory routing table.

### `feature_add_milestone(project_dir, session_id, text)`

Appends a timestamped milestone to the active feature's record. Persisted to the JSON file immediately. Called mid-session when something significant is reached — a working prototype, a key decision made, a subsystem completed. Meant to preserve context that would otherwise exist only in conversation history.

### `feature_list(project_dir)`

Returns all features (active, completed, discarded) with status, dates, session count, and milestone count. Read-only, no `session_id` required.

### `feature_discard(project_dir, session_id)`

Marks the feature as discarded. Moves `features/<name>.md` to `features/_archived/<name>.md` if it exists. Removes the session from the routing table.

---

## REST API (bot-facing)

### `GET /api/projects/{encoded_path}/features`

Returns current feature state for the project — current feature name, status, recent sessions. Used by the bot for system prompt injection and display.

### `POST /api/projects/{encoded_path}/sessions/{session_id}/cost`

```json
{ "cost_usd": 0.04, "input_tokens": 1500, "output_tokens": 80 }
```

Bot calls this after each streaming response. MCP accumulates onto the active feature's totals and persists to the JSON file.

---

## Bot Changes

### Removed
- `core/feature_manager.py` — entirely replaced by MCP
- Feature state logic from `core/state.py`
- The feature lifecycle auto-generated block in `~/.claude/CLAUDE.md`

### Updated
- `discord_cogs/claude_prompt.py` — replace `feature_manager` calls with `GET /api/projects/.../features` for reading state; add `POST .../cost` call after each streaming chunk accumulation
- `discord_cogs/features.py` — slash commands (`/start-feature`, `/resume-feature`, etc.) call REST API instead of `feature_manager`
- `~/.claude/CLAUDE.md` — feature lifecycle block replaced with: *"Call `feature_context` at the start of each session. Use `feature_start`, `feature_resume`, `feature_complete`, `feature_add_milestone`, `feature_list`, and `feature_discard` to manage features. See tool descriptions for full guidance."*

### Unchanged
- Session ID handling in `claude_prompt.py` (still passed to MCP via bot)
- Cost accumulation logic in the streaming loop
- `features/<name>.md` file format
- `.claude/features/*.json` file format (additive changes only)

---

## Startup & Operations

The MCP server is a Windows process that should start with the machine (or be started manually before Claude sessions begin). A simple `start.bat` or Windows Task Scheduler entry is sufficient for now.

On startup:
1. Scan all known project dirs for active features
2. Rebuild in-memory session routing table
3. Start FastAPI server on port 8765
4. Log which features were restored

Known project dirs are configured via an env var or a simple `projects.json` config file at `M:\feature-mcp\projects.json`:
```json
["M:/bridgecrew", "M:/mappa", "M:/myvillage-agents", "M:/myvillage-apps", "M:/nms-helper", "M:/plio-max", "M:/sbi"]
```

---

## Error Handling

- **Server not running:** Claude sessions fail gracefully — `feature_context` returns an error, Claude notes it and continues without feature tracking rather than halting
- **Project dir not found:** tool returns descriptive error, no file operations attempted
- **Concurrent writes:** all file writes use atomic replace (write to `.tmp`, rename) — same pattern as current `core/state.py`
- **Stale in-memory state:** if a session ID in memory has no matching active JSON file, it's pruned on next access

---

## Out of Scope (this iteration)

- Web UI for the MCP server
- Feature branching / sub-features
- Cross-project feature linking
- Automatic session staleness detection (timeout-based abandonment)
