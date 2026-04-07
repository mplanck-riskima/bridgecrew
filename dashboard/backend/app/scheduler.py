"""Background scheduler — evaluates cron expressions and auto-dispatches tasks."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="America/Los_Angeles")
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
    # Guard against the window between a disable mutation and the next reload_schedules() call
    if not task.get("enabled", False):
        log.warning("Task %s fired but is now disabled — skipping (reload pending)", task_id)
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
                timezone="America/Los_Angeles",
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
    if not scheduler.running:
        scheduler.start()
        log.info("APScheduler started")
    reload_schedules()


def stop() -> None:
    """Gracefully shut down the scheduler."""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("APScheduler stopped")
