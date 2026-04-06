"""Scheduled task CRUD and dispatch endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx
from bson import ObjectId
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.db import scheduled_tasks_col

log = logging.getLogger(__name__)

router = APIRouter(tags=["schedules"])


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


class ScheduleCreate(BaseModel):
    name: str
    project_id: str = ""
    prompt: str
    prompt_template_id: str = ""
    discord_channel_id: str = ""
    cron_expr: str
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    name: str | None = None
    project_id: str | None = None
    prompt: str | None = None
    prompt_template_id: str | None = None
    discord_channel_id: str | None = None
    cron_expr: str | None = None
    enabled: bool | None = None


@router.get("/schedules")
def list_schedules() -> list[dict]:
    """Return all scheduled tasks."""
    return [_serialize(doc) for doc in scheduled_tasks_col().find()]


@router.post("/schedules", status_code=201)
def create_schedule(body: ScheduleCreate) -> dict:
    """Create a new scheduled task."""
    doc = {
        "name": body.name,
        "project_id": body.project_id,
        "prompt": body.prompt,
        "prompt_template_id": body.prompt_template_id,
        "discord_channel_id": body.discord_channel_id,
        "cron_expr": body.cron_expr,
        "enabled": body.enabled,
        "last_run": None,
        "last_status": "unknown",
    }
    result = scheduled_tasks_col().insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    return doc


@router.put("/schedules/{schedule_id}")
def update_schedule(schedule_id: str, body: ScheduleUpdate) -> dict:
    """Update a scheduled task."""
    try:
        oid = ObjectId(schedule_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid schedule ID")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = scheduled_tasks_col().update_one({"_id": oid}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Schedule not found")

    doc = scheduled_tasks_col().find_one({"_id": oid})
    return _serialize(doc)


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: str) -> None:
    """Delete a scheduled task."""
    try:
        oid = ObjectId(schedule_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid schedule ID")
    result = scheduled_tasks_col().delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Schedule not found")


@router.post("/schedules/{schedule_id}/trigger")
async def trigger_schedule(schedule_id: str) -> dict:
    """Manually fire a scheduled task — posts its prompt to the configured Discord channel."""
    try:
        oid = ObjectId(schedule_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid schedule ID")

    task = scheduled_tasks_col().find_one({"_id": oid})
    if task is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    prompt = task.get("prompt", "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Schedule has no prompt configured")

    # Resolve bot ID: use configured value or fetch from Discord API
    bot_id = await _get_bot_id()
    mention = f"<@{bot_id}> " if bot_id else ""
    persona_marker = f"\n[persona:{task['prompt_template_id']}]" if task.get("prompt_template_id") else ""
    full_prompt = f"{mention}{prompt}\n\n[scheduled-order]{persona_marker}"

    channel_id = task.get("discord_channel_id") or settings.DISCORD_CHANNEL_ID
    if not channel_id:
        raise HTTPException(status_code=400, detail="No discord_channel_id on task and DISCORD_CHANNEL_ID not configured")

    status, detail = await _dispatch_to_discord(channel_id, full_prompt)

    scheduled_tasks_col().update_one(
        {"_id": oid},
        {"$set": {"last_run": datetime.now(UTC), "last_status": status}},
    )
    result: dict = {"status": status, "channel_id": channel_id}
    if detail:
        result["detail"] = detail
    return result


_cached_bot_id: str | None = None


async def _get_bot_id() -> str:
    """Fetch and cache the bot's own Discord user ID via GET /users/@me."""
    global _cached_bot_id
    if _cached_bot_id:
        return _cached_bot_id
    if not settings.DISCORD_TOKEN:
        return ""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bot {settings.DISCORD_TOKEN}"},
            )
        if resp.status_code == 200:
            _cached_bot_id = resp.json()["id"]
            log.info("Resolved bot ID: %s", _cached_bot_id)
            return _cached_bot_id
        log.warning("Failed to resolve bot ID: HTTP %s", resp.status_code)
    except Exception as exc:
        log.warning("Failed to resolve bot ID: %s", exc)
    return ""


async def _dispatch_to_discord(channel_id: str, content: str) -> tuple[str, str]:
    """POST a message to a Discord channel via the REST API.

    Returns (status, detail) where status is 'dispatched', 'skipped', or 'failed'.
    """
    if not settings.DISCORD_TOKEN:
        log.warning("DISCORD_TOKEN not set — skipping Discord dispatch")
        return "skipped", "DISCORD_TOKEN not configured"

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {settings.DISCORD_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"content": content}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code in (200, 201):
            return "dispatched", ""
        detail = f"HTTP {resp.status_code}: {resp.text}"
        log.error("Discord API error %s: %s", resp.status_code, resp.text)
        return "failed", detail
    except Exception as exc:
        log.error("Discord dispatch failed: %s", exc)
        return "failed", str(exc)
