"""Project maintainer CRUD, dispatch, and prompt builder."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import scheduler as sched
from app.db import project_maintainers_col, projects_col
from app.routers.schedules import _dispatch_to_discord, _get_bot_id

log = logging.getLogger(__name__)

router = APIRouter(tags=["maintainers"])


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


class MaintainerCreate(BaseModel):
    project_id: str
    name: str
    cron_expr: str
    enabled: bool = True
    log_sources: str
    detection_instructions: str
    fix_instructions: str
    log_ttl_days: int = 7


class MaintainerUpdate(BaseModel):
    name: str | None = None
    cron_expr: str | None = None
    enabled: bool | None = None
    log_sources: str | None = None
    detection_instructions: str | None = None
    fix_instructions: str | None = None
    log_ttl_days: int | None = None


@router.get("/maintainers")
def list_maintainers(project_id: str) -> list[dict]:
    """Return all maintainers for a project."""
    return [_serialize(doc) for doc in project_maintainers_col().find({"project_id": project_id})]


@router.post("/maintainers", status_code=201)
async def create_maintainer(body: MaintainerCreate) -> dict:
    """Create a new project maintainer."""
    doc = {
        "project_id": body.project_id,
        "name": body.name,
        "cron_expr": body.cron_expr,
        "enabled": body.enabled,
        "log_sources": body.log_sources,
        "detection_instructions": body.detection_instructions,
        "fix_instructions": body.fix_instructions,
        "log_ttl_days": body.log_ttl_days,
        "last_run": None,
        "last_status": "unknown",
        "created_at": datetime.now(UTC),
    }
    result = project_maintainers_col().insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    sched.reload_schedules()
    return doc


@router.put("/maintainers/{maintainer_id}")
async def update_maintainer(maintainer_id: str, body: MaintainerUpdate) -> dict:
    """Update a project maintainer."""
    try:
        oid = ObjectId(maintainer_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid maintainer ID")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = project_maintainers_col().update_one({"_id": oid}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Maintainer not found")

    doc = project_maintainers_col().find_one({"_id": oid})
    sched.reload_schedules()
    return _serialize(doc)


@router.delete("/maintainers/{maintainer_id}", status_code=204)
async def delete_maintainer(maintainer_id: str) -> None:
    """Delete a project maintainer."""
    try:
        oid = ObjectId(maintainer_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid maintainer ID")
    result = project_maintainers_col().delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Maintainer not found")
    sched.reload_schedules()


@router.post("/maintainers/{maintainer_id}/trigger")
async def trigger_maintainer(maintainer_id: str) -> dict:
    """Manually fire a maintainer run."""
    try:
        oid = ObjectId(maintainer_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid maintainer ID")

    task = project_maintainers_col().find_one({"_id": oid})
    if task is None:
        raise HTTPException(status_code=404, detail="Maintainer not found")

    status, detail = await _run_maintainer(task)
    result: dict = {"status": status}
    if detail:
        result["detail"] = detail
    return result


def _build_prompt(project_name: str, maintainer: dict) -> str:
    """Build the dispatch prompt from maintainer config."""
    ttl = maintainer.get("log_ttl_days", 7)
    return (
        f"You are the automated maintainer for project {project_name}.\n\n"
        f"Log sources to check:\n{maintainer['log_sources']}\n\n"
        f"How to detect if something went wrong:\n{maintainer['detection_instructions']}\n\n"
        f"How to fix issues when found:\n{maintainer['fix_instructions']}\n\n"
        f"Review the logs, apply the detection criteria, fix any issues found, "
        f"and report your findings.\n\n"
        f"[scheduled-order][maintainer-run:{ttl}]"
    )


async def _run_maintainer(task: dict) -> tuple[str, str]:
    """Core dispatch logic for a maintainer run."""
    project_id = task.get("project_id", "")
    project = projects_col().find_one({"project_id": project_id}, {"_id": 0})
    if project is None:
        log.warning("Maintainer %s: project %s not found", task.get("_id"), project_id)
        return "failed", f"project {project_id} not found"

    project_name = project.get("name", project_id)
    channel_id = project.get("discord_channel_id", "")
    if not channel_id:
        from app.config import settings
        channel_id = settings.DISCORD_CHANNEL_ID
    if not channel_id:
        return "failed", "no discord_channel_id on project and DISCORD_CHANNEL_ID not configured"

    bot_id = await _get_bot_id()
    mention = f"<@{bot_id}> " if bot_id else ""
    prompt = _build_prompt(project_name, task)
    full_content = f"{mention}{prompt}"

    status, detail = await _dispatch_to_discord(channel_id, full_content)

    project_maintainers_col().update_one(
        {"_id": task["_id"]},
        {"$set": {"last_run": datetime.now(UTC), "last_status": status}},
    )
    return status, detail
