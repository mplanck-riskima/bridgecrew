# Project Maintainers — Design Spec

**Date:** 2026-05-18  
**Feature:** project-maintainers  
**Status:** Approved

---

## Overview

A per-project scheduled maintainer that checks web app logs, identifies issues, and autonomously applies fixes. Maintainers are configured in the dashboard and dispatched via the existing APScheduler + Discord bot pipeline.

---

## 1. Data Model

New MongoDB collection: `project_maintainers`

```
Field                  Type      Default    Description
---------------------  --------  ---------  ------------------------------------------
project_id             str       required   References projects collection
name                   str       required   Display name ("Daily Log Check")
cron_expr              str       required   5-field cron ("0 9 * * *")
enabled                bool      true       Whether to auto-fire on schedule
log_sources            str       required   Where to find logs (free-text)
detection_instructions str       required   How to determine if something went wrong
fix_instructions       str       required   What to do when an issue is detected
log_ttl_days           int       7          Days to retain activity log entries
last_run               datetime  null       Populated after each run
last_status            str       "unknown"  "unknown"|"dispatched"|"failed"|"skipped"
created_at             datetime  now        Creation timestamp
```

**Notes:**
- Multiple maintainers per project are supported (e.g. daily log check + weekly dep audit).
- No `discord_channel_id` override — the dispatcher resolves the channel from the project record.

---

## 2. API

New router: `dashboard/backend/app/routers/maintainers.py`, mounted at `/api/maintainers`.

```
GET    /api/maintainers?project_id=...   List maintainers for a project
POST   /api/maintainers                  Create (triggers scheduler reload)
PUT    /api/maintainers/{id}             Update (triggers scheduler reload)
DELETE /api/maintainers/{id}             Delete (triggers scheduler reload)
POST   /api/maintainers/{id}/trigger     Manual run
```

CRUD mutations call `reload_schedules()` in `scheduler.py` after write, identical to how schedule mutations work today.

---

## 3. Scheduler

`scheduler.py`'s `reload_schedules()` is extended to also load maintainer jobs from `project_maintainers`. Each maintainer gets an APScheduler job keyed as `maintainer:{id}`. On fire, it calls a shared `_run_maintainer(maintainer_id)` that:

1. Loads the maintainer doc and its associated project doc from MongoDB.
2. Resolves the project's Discord channel ID.
3. Builds the dispatch prompt (see Section 4).
4. Calls `_dispatch_to_discord(channel_id, prompt)` — same function used by scheduled tasks.
5. Updates `last_run` and `last_status` on the maintainer doc.

---

## 4. Prompt Construction

The backend assembles the prompt from config fields:

```
You are the automated maintainer for project {project_name}.

Log sources to check:
{log_sources}

How to detect if something went wrong:
{detection_instructions}

How to fix issues when found:
{fix_instructions}

Review the logs, apply the detection criteria, fix any issues found, and report your findings.

[scheduled-order][maintainer-run:{log_ttl_days}]
```

The `[scheduled-order]` marker causes the bot to process the message from its own account and bypass the captain role gate. The `[maintainer-run:N]` marker carries the retention TTL for activity log entries.

---

## 5. Activity Log Retention

**Bot side:** When `on_message()` detects `[maintainer-run:N]`, it parses `N` and stores it on the queued prompt context.

**Client side:** `BridgecrewClient.report_activity()` gains an optional `ttl_days` parameter. Maintainer runs pass `ttl_days=N` to every `report_activity()` call during that run.

**Backend side:** `POST /api/activity` gains an optional `ttl_days` body field. When present:
- `expires_at = created_at + timedelta(days=ttl_days)` is written onto the document.
- A sparse TTL index on `expires_at` handles cleanup.

Existing activity entries (no `expires_at` field) are unaffected; they continue to use the global 7-day TTL index on `created_at`. Maintainer entries are caught by whichever index fires first based on their configured TTL.

---

## 6. Dashboard UI

New **"Maintainer"** tab in the project detail page.

**Tab contents:**
- List of maintainer cards, each showing: name, human-readable cron, enabled status, last run time, last run status badge.
- **Add Maintainer** button → inline form with:
  - Name (text input)
  - Schedule (reuses existing `CronInput` component)
  - Log Sources (textarea)
  - Detection Instructions (textarea)
  - Fix Instructions (textarea)
  - Log Retention in days (number input)
  - Enabled toggle
- Per-card actions: Edit, Delete, Run Now.
- **Run Now** calls `POST /api/maintainers/{id}/trigger` and shows a toast confirmation.

Maintainer activity entries in the project activity feed are visually tagged (e.g. wrench icon + "Maintainer" label) to distinguish them from regular chat and feature activity.

---

## 7. Bot Changes

`discord_cogs/claude_prompt.py`:

1. Extend `[scheduled-order]` detection to also strip `[maintainer-run:N]` from the message before passing to Claude.
2. Parse `N` from the marker and store as `maintainer_ttl_days` on the `QueuedPrompt` context.
3. Pass `ttl_days=maintainer_ttl_days` to all `report_activity()` calls made during the run.

No changes to the role gate logic — `is_self` remains the sole security check for dispatch bypass, consistent with how scheduled orders work today.

---

## Affected Files

```
NEW
  dashboard/backend/app/routers/maintainers.py
  dashboard/frontend/src/pages/MaintainerTab.tsx   (or component)

MODIFIED
  dashboard/backend/app/scheduler.py               extend reload_schedules()
  dashboard/backend/app/routers/activity.py        add ttl_days to POST /api/activity
  dashboard/backend/app/main.py                    register maintainers router
  dashboard/frontend/src/lib/types.ts              add ProjectMaintainer type
  dashboard/frontend/src/pages/ProjectDetail.tsx   add Maintainer tab
  core/bridgecrew_client.py                        add ttl_days to report_activity()
  discord_cogs/claude_prompt.py                    parse [maintainer-run:N] marker
```
