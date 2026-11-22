"""Scheduled order CRUD and dispatch endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx
from bson import ObjectId
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import scheduler as sched
from app.config import settings
from app.db import orders_col, prompt_templates_col

log = logging.getLogger(__name__)

router = APIRouter(tags=["orders"])


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


class OrderCreate(BaseModel):
    name: str
    project_id: str = ""
    prompt: str
    prompt_template_id: str = ""
    discord_channel_id: str = ""
    cron_expr: str
    enabled: bool = True
    feature_name: str = ""


class OrderUpdate(BaseModel):
    name: str | None = None
    project_id: str | None = None
    prompt: str | None = None
    prompt_template_id: str | None = None
    discord_channel_id: str | None = None
    cron_expr: str | None = None
    enabled: bool | None = None
    feature_name: str | None = None


@router.get("/orders")
def list_orders() -> list[dict]:
    """Return all scheduled orders."""
    return [_serialize(doc) for doc in orders_col().find()]


@router.post("/orders", status_code=201)
async def create_order(body: OrderCreate) -> dict:
    """Create a new scheduled order."""
    doc = {
        "name": body.name,
        "project_id": body.project_id,
        "prompt": body.prompt,
        "prompt_template_id": body.prompt_template_id,
        "discord_channel_id": body.discord_channel_id,
        "cron_expr": body.cron_expr,
        "enabled": body.enabled,
        "feature_name": body.feature_name,
        "last_run": None,
        "last_status": "unknown",
    }
    result = orders_col().insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    sched.reload_schedules()
    return doc


@router.put("/orders/{order_id}")
async def update_order(order_id: str, body: OrderUpdate) -> dict:
    """Update a scheduled order."""
    try:
        oid = ObjectId(order_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid order ID")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = orders_col().update_one({"_id": oid}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Order not found")

    doc = orders_col().find_one({"_id": oid})
    sched.reload_schedules()
    return _serialize(doc)


@router.delete("/orders/{order_id}", status_code=204)
async def delete_order(order_id: str) -> None:
    """Delete a scheduled order."""
    try:
        oid = ObjectId(order_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid order ID")
    result = orders_col().delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Order not found")
    sched.reload_schedules()


async def _run_task(task: dict) -> tuple[str, str]:
    """Core dispatch logic shared by manual trigger and the scheduler.

    Returns (status, detail).
    """
    prompt = task.get("prompt", "").strip()
    if not prompt:
        return "skipped", "no prompt configured"

    bot_id = await _get_bot_id()
    mention = f"<@{bot_id}> " if bot_id else ""
    if task.get("prompt_template_id"):
        tmpl = prompt_templates_col().find_one({"_id": ObjectId(task["prompt_template_id"])}, {"name": 1})
        persona_name = (tmpl.get("name") or "").strip() if tmpl else ""
        persona_suffix = f"|{persona_name}" if persona_name else ""
        persona_marker = f"\n[persona:{task['prompt_template_id']}{persona_suffix}]"
        persona_label_marker = f"\n[persona-label:{persona_name}]" if persona_name else ""
    else:
        persona_marker = ""
        persona_label_marker = ""
    project_marker = f"\n[scheduled-project:{task['project_id']}]" if task.get("project_id") else ""
    order_id_marker = f"\n[order-id:{str(task['_id'])}]"
    order_feature_marker = f"\n[order-feature:{task['feature_name']}]" if task.get("feature_name") else ""
    full_prompt = (
        f"{mention}{prompt}\n\n[order]"
        f"{persona_marker}{persona_label_marker}{project_marker}"
        f"{order_id_marker}{order_feature_marker}"
    )

    channel_id = task.get("discord_channel_id") or settings.DISCORD_CHANNEL_ID
    if not channel_id:
        return "failed", "no discord_channel_id and DISCORD_CHANNEL_ID not configured"

    status, detail = await _dispatch_to_discord(channel_id, full_prompt)

    orders_col().update_one(
        {"_id": task["_id"]},
        {"$set": {"last_run": datetime.now(UTC), "last_status": status}},
    )
    return status, detail


@router.post("/orders/{order_id}/trigger")
async def trigger_order(order_id: str) -> dict:
    """Manually fire a scheduled order."""
    try:
        oid = ObjectId(order_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid order ID")

    task = orders_col().find_one({"_id": oid})
    if task is None:
        raise HTTPException(status_code=404, detail="Order not found")

    if not task.get("prompt", "").strip():
        raise HTTPException(status_code=400, detail="Order has no prompt configured")

    status, detail = await _run_task(task)
    channel_id = task.get("discord_channel_id") or settings.DISCORD_CHANNEL_ID or ""
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
