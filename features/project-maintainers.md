# project-maintainers

**Started:** 2026-05-18  
**Completed:** 2026-05-19  
**Cost:** $6.9133

## Summary

## Project Maintainers

Adds per-project scheduled maintainer scripts to the Discord Claude Bot — automated health-check agents that inspect logs, detect issues, and optionally fix them on a configurable cron schedule.

### What was built

**Backend (FastAPI + MongoDB):**
- New `project_maintainers` MongoDB collection with fields: `project_id`, `name`, `cron_expr`, `enabled`, `log_sources`, `detection_instructions`, `fix_instructions`, `log_ttl_days`, `last_run`, `last_status`, `created_at`
- Full CRUD router at `/api/maintainers` (`dashboard/backend/app/routers/maintainers.py`) with create, list, update, delete, and trigger endpoints
- `_build_prompt()` constructs the dispatch prompt from the three config fields; `_run_maintainer()` looks up the project's Discord channel and dispatches via the existing `_dispatch_to_discord` mechanism
- APScheduler extended (`scheduler.py`) to load maintainer jobs alongside scheduled tasks, keyed `maintainer:{id}`
- Activity log TTL extended: a sparse `expires_at` index (expireAfterSeconds=0) on the activity collection allows per-maintainer-run retention independent of the global 7-day TTL

**Bot (discord_cogs/claude_prompt.py):**
- Parses `[maintainer-run:N]` marker to extract TTL days and strips it before Claude sees the prompt
- Both `report_activity` calls use a `lambda ttl=maintainer_ttl_days:` capture to correctly propagate TTL
- Auto-registers a project's Discord channel ID into MongoDB the first time the bot processes a message in that project thread (one-time via `discord_channel_registered` state flag)

**Dashboard client (core/bridgecrew_client.py):**
- Added `update_project()` for bot→dashboard project field updates
- Added `ttl_days` parameter to `report_activity()`

**Frontend (React + TypeScript):**
- `ProjectMaintainer` TypeScript interface and 5 API client methods in `api.ts`
- New `MaintainerTab.tsx` component: full CRUD form (Name, Schedule via CronInput, Log Sources, Detection Instructions, Fix Instructions, Log Retention, Enabled), maintainer card list with color-coded status, RUN NOW with transient result, EDIT, DELETE
- "MAINTAINER" tab integrated into `ProjectDetail.tsx`

### Key technical decisions
- Dispatch reuses `[scheduled-order]` marker for bot self-processing with `is_self` security check rather than a new auth mechanism
- No `discord_channel_id` on the maintainer model — looked up from the project at runtime, with fallback to `settings.DISCORD_CHANNEL_ID`
- Sparse TTL index on `expires_at` avoids touching existing activity documents and coexists cleanly with the global `created_at` TTL

### Known gaps / follow-up
- Pre-existing auth test failures (4 tests in `test_auth.py`) are unrelated to this feature — from the oauth-dashboard feature
- Minor: `_add_cron_job` helper could eliminate the duplicated cron-parse block in `scheduler.py`
- Minor: `safeDescribe` in `MaintainerTab.tsx` duplicates logic from `CronInput` — could be extracted to `lib/cron.ts`
