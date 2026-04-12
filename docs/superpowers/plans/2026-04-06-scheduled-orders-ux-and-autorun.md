# Scheduled Orders — Cron UX & Auto-Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the cron expression field user-friendly (presets + live preview), and implement an automatic background scheduler so saved cron expressions actually execute without manual triggering.

**Architecture:** A new `CronInput` React component replaces the raw text field with preset buttons, a human-readable preview (via `cronstrue`), and inline validation. On the backend, an `APScheduler AsyncIOScheduler` is started in the FastAPI lifespan and reloaded whenever schedules are created/updated/deleted, so enabled schedules fire automatically at their configured times.

**Tech Stack:** React 19 + TypeScript, `cronstrue` (npm), FastAPI lifespan, `apscheduler>=3.10` (pip), existing MongoDB + Discord dispatch code.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `dashboard/frontend/src/components/CronInput.tsx` | **Create** | Self-contained cron input: presets, text input, preview, validation |
| `dashboard/frontend/src/pages/Schedules.tsx` | **Modify** | Replace raw cron `<input>` with `<CronInput>`, show preview in card display |
| `dashboard/backend/requirements.txt` | **Modify** | Add `apscheduler>=3.10.4` |
| `dashboard/backend/app/scheduler.py` | **Create** | AsyncIOScheduler singleton, `reload_schedules()` that syncs MongoDB → APScheduler jobs |
| `dashboard/backend/app/routers/schedules.py` | **Modify** | Extract `_run_task(task_doc)` helper; call `reload_schedules()` after CRUD changes |
| `dashboard/backend/app/main.py` | **Modify** | Start/stop scheduler in lifespan |

---

## Task 1: Install `cronstrue` and create `CronInput` component

**Files:**
- Create: `dashboard/frontend/src/components/CronInput.tsx`

- [ ] **Step 1: Install cronstrue**

```bash
cd dashboard/frontend && npm install cronstrue
```

Expected: `cronstrue` appears in `package.json` dependencies.

- [ ] **Step 2: Create `CronInput.tsx`**

```tsx
// dashboard/frontend/src/components/CronInput.tsx
import cronstrue from "cronstrue";
import { useState } from "react";

const PRESETS = [
  { label: "Hourly",         value: "0 * * * *" },
  { label: "Daily 9 AM",     value: "0 9 * * *" },
  { label: "Daily Midnight", value: "0 0 * * *" },
  { label: "Mon 9 AM",       value: "0 9 * * 1" },
  { label: "Monthly 1st",    value: "0 9 1 * *" },
];

interface Props {
  value: string;
  onChange: (val: string) => void;
  className?: string;
}

function describeOrError(expr: string): { preview: string; error: string } {
  if (!expr.trim()) return { preview: "", error: "" };
  try {
    return { preview: cronstrue.toString(expr, { use24HourTimeFormat: false }), error: "" };
  } catch {
    return { preview: "", error: "Invalid cron expression" };
  }
}

export default function CronInput({ value, onChange, className = "" }: Props) {
  const [focused, setFocused] = useState(false);
  const { preview, error } = describeOrError(value);

  const inputCls =
    "w-full bg-lcars-panel border text-lcars-text font-mono text-sm px-3 py-2 focus:outline-none placeholder:text-lcars-muted " +
    (error ? "border-lcars-red" : focused ? "border-lcars-orange" : "border-lcars-border");

  return (
    <div className={className}>
      {/* Preset buttons */}
      <div className="flex flex-wrap gap-1 mb-2">
        {PRESETS.map((p) => (
          <button
            key={p.value}
            type="button"
            onClick={() => onChange(p.value)}
            className={
              "px-2 py-0.5 text-xs font-mono tracking-widest border transition-colors " +
              (value === p.value
                ? "bg-lcars-orange text-black border-lcars-orange"
                : "border-lcars-border text-lcars-muted hover:border-lcars-orange hover:text-lcars-orange")
            }
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Raw input */}
      <input
        className={inputCls}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        placeholder="0 9 * * *"
        spellCheck={false}
      />

      {/* Live preview / error */}
      <div className="mt-1 text-xs font-mono h-4">
        {error ? (
          <span className="text-lcars-red">{error}</span>
        ) : preview ? (
          <span className="text-lcars-muted">{preview}</span>
        ) : null}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify it renders in isolation**

Open `Schedules.tsx`, temporarily swap the cron `<input>` block with:
```tsx
import CronInput from "../components/CronInput";
// ...
<CronInput value={form.cron_expr} onChange={(v) => setForm((f) => ({ ...f, cron_expr: v }))} />
```
Start dev server (`npm run dev`) and confirm presets appear, preview updates as you type, and red error shows for garbage input like `99 99 99`.

---

## Task 2: Wire `CronInput` into `Schedules.tsx` and update the card display

**Files:**
- Modify: `dashboard/frontend/src/pages/Schedules.tsx`

- [ ] **Step 1: Replace the cron form field**

In `Schedules.tsx`, remove the current cron block (lines 162–169):
```tsx
<div>
  <label className={labelCls}>Cron Expression</label>
  <input
    className={inputCls}
    value={form.cron_expr}
    onChange={(e) => setForm((f) => ({ ...f, cron_expr: e.target.value }))}
    placeholder="0 9 * * *"
  />
</div>
```

Replace with:
```tsx
import CronInput from "../components/CronInput";

// inside JSX grid:
<div>
  <label className={labelCls}>Cron Expression</label>
  <CronInput
    value={form.cron_expr}
    onChange={(v) => setForm((f) => ({ ...f, cron_expr: v }))}
  />
</div>
```

- [ ] **Step 2: Add cron validation to the Save button**

Add a `cronValid` derived variable and disable Save when invalid:
```tsx
import cronstrue from "cronstrue";

function isCronValid(expr: string): boolean {
  if (!expr.trim()) return false;
  try { cronstrue.toString(expr); return true; }
  catch { return false; }
}

// In JSX, update the Save button disabled condition:
disabled={saving || !form.name || !form.prompt || !isCronValid(form.cron_expr)}
```

- [ ] **Step 3: Show human-readable preview in each schedule card**

In the card display section (currently shows raw `s.cron_expr` at line 277), add a preview line below the raw cron:
```tsx
import cronstrue from "cronstrue";

function safeDescribe(expr: string): string {
  try { return cronstrue.toString(expr, { use24HourTimeFormat: false }); }
  catch { return ""; }
}

// In the card CRON display block:
<div>
  <span className="text-lcars-muted tracking-widest">CRON</span>
  <div className="text-lcars-amber mt-0.5">{s.cron_expr}</div>
  {safeDescribe(s.cron_expr) && (
    <div className="text-lcars-muted text-[10px] mt-0.5">{safeDescribe(s.cron_expr)}</div>
  )}
</div>
```

- [ ] **Step 4: Verify in browser**

Run `npm run dev`. Confirm:
- Preset buttons appear and populate the field
- Preview text appears below the input as you type
- Cards show human-readable description under the raw cron
- Save button stays disabled until cron is valid

- [ ] **Step 5: Commit**

```bash
cd M:/bridgecrew
git add dashboard/frontend/src/components/CronInput.tsx dashboard/frontend/src/pages/Schedules.tsx dashboard/frontend/package.json dashboard/frontend/package-lock.json
git commit -m "feat: add cron presets, live preview, and validation to Schedules UI"
```

---

## Task 3: Add APScheduler to backend requirements

**Files:**
- Modify: `dashboard/backend/requirements.txt`

- [ ] **Step 1: Add the dependency**

Add to `dashboard/backend/requirements.txt`:
```
apscheduler>=3.10.4
```

Final file should be:
```
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
pymongo>=4.10.0
pydantic>=2.10.0
pydantic-settings>=2.0.0
python-ulid>=2.0.0
python-dotenv>=1.0.0
httpx>=0.27.0
apscheduler>=3.10.4
```

- [ ] **Step 2: Install**

```bash
cd M:/bridgecrew/dashboard/backend
pip install apscheduler>=3.10.4
```

Expected: `Successfully installed apscheduler-3.x.x`

---

## Task 4: Extract `_run_task` dispatch helper in `schedules.py`

The manual trigger endpoint and the scheduler will share the same dispatch logic. Extract it now so there's no duplication.

**Files:**
- Modify: `dashboard/backend/app/routers/schedules.py`

- [ ] **Step 1: Extract `_run_task` from `trigger_schedule`**

Add this function above `trigger_schedule` (after `_dispatch_to_discord`):

```python
async def _run_task(task: dict) -> tuple[str, str]:
    """Core dispatch logic shared by manual trigger and the scheduler.

    Returns (status, detail).
    """
    from app.db import scheduled_tasks_col
    from bson import ObjectId

    prompt = task.get("prompt", "").strip()
    if not prompt:
        return "skipped", "no prompt configured"

    bot_id = await _get_bot_id()
    mention = f"<@{bot_id}> " if bot_id else ""
    persona_marker = f"\n[persona:{task['prompt_template_id']}]" if task.get("prompt_template_id") else ""
    full_prompt = f"{mention}{prompt}\n\n[scheduled-order]{persona_marker}"

    channel_id = task.get("discord_channel_id") or settings.DISCORD_CHANNEL_ID
    if not channel_id:
        return "failed", "no discord_channel_id and DISCORD_CHANNEL_ID not configured"

    status, detail = await _dispatch_to_discord(channel_id, full_prompt)

    scheduled_tasks_col().update_one(
        {"_id": task["_id"]},
        {"$set": {"last_run": datetime.now(UTC), "last_status": status}},
    )
    return status, detail
```

- [ ] **Step 2: Simplify `trigger_schedule` to use `_run_task`**

Replace the body of `trigger_schedule` with:
```python
@router.post("/schedules/{schedule_id}/trigger")
async def trigger_schedule(schedule_id: str) -> dict:
    """Manually fire a scheduled task."""
    try:
        oid = ObjectId(schedule_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid schedule ID")

    task = scheduled_tasks_col().find_one({"_id": oid})
    if task is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    status, detail = await _run_task(task)
    channel_id = task.get("discord_channel_id") or settings.DISCORD_CHANNEL_ID or ""
    result: dict = {"status": status, "channel_id": channel_id}
    if detail:
        result["detail"] = detail
    return result
```

- [ ] **Step 3: Verify manual trigger still works**

Start the backend locally and POST to `/api/schedules/{id}/trigger` for an existing schedule. Confirm the Discord message still fires.

---

## Task 5: Create `app/scheduler.py`

**Files:**
- Create: `dashboard/backend/app/scheduler.py`

- [ ] **Step 1: Write the scheduler module**

```python
"""Background scheduler — evaluates cron expressions and auto-dispatches tasks."""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


async def _fire_task(task_id: str) -> None:
    """Load task from DB and dispatch. Called by APScheduler."""
    from bson import ObjectId

    from app.db import scheduled_tasks_col
    from app.routers.schedules import _run_task

    task = scheduled_tasks_col().find_one({"_id": ObjectId(task_id)})
    if task is None:
        log.warning("Scheduled task %s not found in DB — skipping", task_id)
        return
    if not task.get("enabled", False):
        log.info("Task %s is disabled — skipping", task_id)
        return

    log.info("Auto-firing scheduled task: %s", task.get("name", task_id))
    status, detail = await _run_task(task)
    log.info("Task %s result: %s %s", task_id, status, detail)


def reload_schedules() -> None:
    """Sync all enabled schedules from MongoDB into APScheduler.

    Safe to call at any time — removes all existing jobs and re-adds from DB.
    """
    from app.db import scheduled_tasks_col

    scheduler = get_scheduler()

    # Remove all existing managed jobs
    for job in scheduler.get_jobs():
        job.remove()

    tasks = list(scheduled_tasks_col().find({"enabled": True}))
    for task in tasks:
        task_id = str(task["_id"])
        cron_expr = task.get("cron_expr", "").strip()
        if not cron_expr:
            continue
        try:
            parts = cron_expr.split()
            if len(parts) != 5:
                raise ValueError(f"expected 5 fields, got {len(parts)}")
            minute, hour, day, month, day_of_week = parts
            trigger = CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                timezone="UTC",
            )
            scheduler.add_job(
                _fire_task,
                trigger=trigger,
                args=[task_id],
                id=task_id,
                name=task.get("name", task_id),
                replace_existing=True,
                misfire_grace_time=60,
            )
            log.info("Scheduled job '%s' (%s)", task.get("name"), cron_expr)
        except Exception as exc:
            log.warning("Skipping task %s — invalid cron '%s': %s", task_id, cron_expr, exc)

    log.info("Scheduler reload complete: %d job(s) active", len(scheduler.get_jobs()))


def start() -> None:
    """Start the scheduler and load initial jobs."""
    scheduler = get_scheduler()
    reload_schedules()
    if not scheduler.running:
        scheduler.start()
        log.info("APScheduler started")


def stop() -> None:
    """Gracefully shut down the scheduler."""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("APScheduler stopped")
```

---

## Task 6: Wire scheduler into FastAPI lifespan and CRUD hooks

**Files:**
- Modify: `dashboard/backend/app/main.py`
- Modify: `dashboard/backend/app/routers/schedules.py`

- [ ] **Step 1: Update lifespan in `main.py`**

Replace the current empty lifespan:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
```

With:
```python
from app import scheduler as sched

@asynccontextmanager
async def lifespan(app: FastAPI):
    sched.start()
    try:
        yield
    finally:
        sched.stop()
```

- [ ] **Step 2: Call `reload_schedules` after CRUD mutations in `schedules.py`**

Add this import at the top of `schedules.py`:
```python
from app import scheduler as sched
```

In `create_schedule`, add before the `return doc` line:
```python
sched.reload_schedules()
```

In `update_schedule`, add before the final `return _serialize(doc)`:
```python
sched.reload_schedules()
```

In `delete_schedule`, add before the function ends (after the delete_one call):
```python
sched.reload_schedules()
```

- [ ] **Step 3: Verify scheduler starts on boot**

Start the backend:
```bash
cd M:/bridgecrew/dashboard/backend
uvicorn app.main:app --reload
```

Expected log output (if any enabled schedules exist):
```
INFO:app.scheduler:Scheduled job 'Daily health check' (0 9 * * *)
INFO:app.scheduler:Scheduler reload complete: 1 job(s) active
INFO:app.scheduler:APScheduler started
```

If no schedules exist yet, expect:
```
INFO:app.scheduler:Scheduler reload complete: 0 job(s) active
INFO:app.scheduler:APScheduler started
```

- [ ] **Step 4: Create an enabled test schedule via the dashboard and watch logs**

In the Schedules UI, create a schedule with cron `* * * * *` (every minute), save it. Within 60 seconds, expect to see in backend logs:
```
INFO:app.scheduler:Auto-firing scheduled task: Daily health check
INFO:app.scheduler:Task <id> result: dispatched
```
And the Discord message should appear in the configured channel.

Delete the test schedule afterward.

- [ ] **Step 5: Commit**

```bash
cd M:/bridgecrew
git add dashboard/backend/requirements.txt dashboard/backend/app/scheduler.py dashboard/backend/app/main.py dashboard/backend/app/routers/schedules.py
git commit -m "feat: add APScheduler auto-execution for cron schedules"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Cron UX: presets (`CronInput.tsx`)
- [x] Cron UX: live human-readable preview (cronstrue in `CronInput.tsx` and card display)
- [x] Cron UX: inline validation (error state in `CronInput.tsx`, Save button disabled)
- [x] Auto-scheduler: background job runner (`scheduler.py`)
- [x] Auto-scheduler: jobs synced from MongoDB on startup (`lifespan`)
- [x] Auto-scheduler: jobs reloaded on CRUD changes (`reload_schedules()` calls)
- [x] Shared dispatch logic: `_run_task` extracted, used by both manual trigger and scheduler
- [x] Disabled schedules skipped by auto-scheduler

**Placeholder scan:** No TBDs or incomplete steps found.

**Type consistency:** `_run_task(task: dict) -> tuple[str, str]` — used identically in Task 4 (definition) and Task 5 (import + call).
