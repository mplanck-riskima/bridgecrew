# Bugs & Fixes

Catch-all feature session for reliability improvements, UX polish, and fixes that didn't belong to a specific feature initiative.

**Status:** Completed
**Started:** 2026-04-03
**Completed:** 2026-04-06

---

## What it solves

Accumulated fixes and small improvements across the bot and dashboard covering: orphaned subprocess cleanup, prompt footer redesign with real usage data, voice notifier reliability, queued prompt UX, Railway deployment fixes, dashboard activity logging, ask-user loop behavior, and various crash/edge-case fixes.

## Key changes

### Ask-user loop fixes
- **`discord_cogs/claude_prompt.py`** — Open-ended `[ask-user: ...]` questions (no pipe-separated options) now end the prompt sequence immediately; the user's next thread reply continues the session naturally.
- **`discord_cogs/claude_prompt.py`** — Added "Stop — I'll clarify" button to every ask-user widget. Button click or timeout falls through to a best-guess prompt rather than breaking the loop.
- **`discord_cogs/claude_prompt.py`** — Explicit opt-out phrases ("I'll handle it", "let me modify", "I have notes", etc.) typed as a free-text answer break the loop so the user can take over.
- **`core/system_prompt.py`** — Updated `_ASK_USER` instructions to document open-ended vs. button question behavior.

### Dashboard UX
- **`dashboard/frontend/src/pages/ProjectDetail.tsx`** — Activity feed now shows newest entries first; removed auto-scroll to bottom; added "↓ Most Recent First" label.
- **`dashboard/frontend/src/pages/Dashboard.tsx`** — Removed Active Missions count, Total Features count, and per-project feature counts from the mission bridge view.

### Railway deployment
- **`dashboard/Dockerfile`** — Multi-stage build: Vite frontend compiled in Node, FastAPI backend in Python:slim; static files served from `/app/static`.
- **`railway.toml`** — Single-service config with `/health` healthcheck.
- **`dashboard/backend/app/main.py`** — SPA catch-all route so React Router works on refresh/direct URL.

### Dashboard activity logging
- **`core/bridgecrew_client.py`** — Added `get_projects()` and `create_project()` to auto-link Discord projects to the dashboard on sync.
- **`core/project_manager.py`** — `sync_projects()` finds or creates a matching dashboard project for each workspace project, stores `bridgecrew_project_id` in `state.json`.

### Scheduled orders
- **`dashboard/backend/app/routers/schedules.py`** — Added `prompt` field separate from `prompt_template_id` (persona); auto-prepends `<@BOT_ID>` and appends `[scheduled-order]` marker.
- **`core/system_prompt.py`** — `STATIC_SYSTEM_PROMPT_SCHEDULED` replaces ask-user instructions with autonomous-mode instructions when `is_scheduled=True`.

### Startup & env management
- **`startup.sh`** — Default is bot-only; `--with-dash` starts local dashboard; loads `.env.production` vs `.env.local` accordingly.

### Process reliability
- **`core/claude_runner.py`** — Kill entire Claude process tree on cancel (`taskkill /F /T` on Windows, `os.killpg()` on Unix).
- **`core/usage_tracker.py`** — Rolling 5h/daily/weekly token usage from JSONL scan.
- **`core/discord_streamer.py`** — Markdown span continuity across Discord message splits.

## Known limitations / follow-up
- Activity feed still uses a 24h TTL (by design); only the current day's messages appear in the dashboard.
- Cost tracking for plio-max requires verifying `BRIDGECREW_API_URL`/`BRIDGECREW_API_KEY` are set in the bot's runtime environment.
