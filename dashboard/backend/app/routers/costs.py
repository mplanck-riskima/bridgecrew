"""Cost analytics and ingestion endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.db import cost_log_col, projects_col
from app.middleware.api_key import require_api_key

router = APIRouter(tags=["costs"])


class CostCreate(BaseModel):
    """Payload the discord-Claude bot sends after each Claude session."""
    project_id: str = ""
    feature_id: str = ""
    session_id: str = ""
    model: str = ""
    cost_usd: float
    input_tokens: int = 0
    output_tokens: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None


@router.post("/costs", status_code=201)
def ingest_cost(
    body: CostCreate,
    _: None = Depends(require_api_key),
) -> dict:
    """Record a cost entry from the discord-Claude bot."""
    now = datetime.now(UTC)
    doc = {
        "project_id": body.project_id,
        "feature_id": body.feature_id,
        "session_id": body.session_id,
        "model": body.model,
        "cost_usd": body.cost_usd,
        "input_tokens": body.input_tokens,
        "output_tokens": body.output_tokens,
        "started_at": body.started_at or now,
        "completed_at": body.completed_at or now,
    }
    cost_log_col().insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/costs/breakdown")
def cost_breakdown() -> dict:
    """Return total cost aggregated by agent, project, and model."""
    by_agent = list(
        cost_log_col().aggregate([
            {"$group": {"_id": "$agent", "total": {"$sum": "$cost_usd"}}},
            {"$sort": {"total": -1}},
        ])
    )
    by_project_raw = list(
        cost_log_col().aggregate([
            {"$match": {"project_id": {"$ne": ""}}},
            {"$group": {"_id": "$project_id", "total": {"$sum": "$cost_usd"}}},
            {"$sort": {"total": -1}},
        ])
    )

    # Resolve project IDs to human-readable names.
    project_ids = [d["_id"] for d in by_project_raw]
    project_name_map: dict[str, str] = {
        doc["project_id"]: doc["name"]
        for doc in projects_col().find(
            {"project_id": {"$in": project_ids}},
            {"project_id": 1, "name": 1, "_id": 0},
        )
    }
    by_project = [
        {"_id": project_name_map.get(d["_id"], d["_id"]), "total": d["total"]}
        for d in by_project_raw
    ]
    by_model = list(
        cost_log_col().aggregate([
            {"$group": {"_id": "$model", "total": {"$sum": "$cost_usd"}}},
            {"$sort": {"total": -1}},
        ])
    )
    by_category = list(
        cost_log_col().aggregate([
            {"$match": {"category": {"$ne": ""}}},
            {"$group": {"_id": "$category", "total": {"$sum": "$cost_usd"}}},
            {"$sort": {"total": -1}},
        ])
    )

    grand_total = sum(d["total"] for d in by_agent)

    return {
        "total_usd": grand_total,
        "by_agent": {d["_id"]: d["total"] for d in by_agent},
        "by_project": {d["_id"]: d["total"] for d in by_project},
        "by_model": {d["_id"]: d["total"] for d in by_model},
        "by_category": {d["_id"]: d["total"] for d in by_category},
    }


@router.get("/costs/by-agent")
def costs_by_agent(
    agent: str | None = Query(default=None),
) -> list[dict]:
    """Return cost log entries, optionally filtered by agent."""
    query: dict = {}
    if agent:
        query["agent"] = agent

    docs = list(
        cost_log_col()
        .find(query, {"_id": 0})
        .sort("completed_at", -1)
        .limit(500)
    )
    return docs


@router.get("/costs/timeline")
def cost_timeline(
    days: int = Query(default=30, le=365),
) -> list[dict]:
    """Return daily cost totals over time."""
    pipeline = [
        {
            "$group": {
                "_id": {
                    "$dateToString": {"format": "%Y-%m-%d", "date": "$completed_at"},
                },
                "total": {"$sum": "$cost_usd"},
                "count": {"$sum": 1},
            },
        },
        {"$sort": {"_id": 1}},
        {"$project": {"date": "$_id", "total": 1, "count": 1, "_id": 0}},
    ]
    return list(cost_log_col().aggregate(pipeline))
