"""Activity feed — short-term per-project message log (TTL 24 h)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.db import activity_col
from app.middleware.api_key import require_api_key

router = APIRouter(tags=["activity"])

CONTENT_LIMIT = 2000  # chars stored per message


class ActivityCreate(BaseModel):
    project_id: str
    role: str          # "user" | "assistant"
    author: str        # Discord username or "Claude"
    content: str
    feature_name: str | None = None


def _to_out(doc: dict) -> dict:
    return {
        "activity_id": str(doc["_id"]),
        "project_id": doc["project_id"],
        "role": doc["role"],
        "author": doc["author"],
        "content": doc["content"],
        "feature_name": doc.get("feature_name"),
        "created_at": doc["created_at"].isoformat(),
    }


@router.post("/activity", status_code=201)
def ingest_activity(body: ActivityCreate, _: None = Depends(require_api_key)) -> dict:
    doc = {
        "project_id": body.project_id,
        "role": body.role,
        "author": body.author,
        "content": body.content[:CONTENT_LIMIT],
        "feature_name": body.feature_name,
        "created_at": datetime.now(timezone.utc),
    }
    result = activity_col().insert_one(doc)
    doc["_id"] = result.inserted_id
    return _to_out(doc)


@router.get("/projects/{project_id}/activity")
def get_project_activity(project_id: str, limit: int = 50) -> list[dict]:
    docs = (
        activity_col()
        .find({"project_id": project_id})
        .sort("created_at", -1)
        .limit(min(limit, 200))
    )
    # Return in chronological order for display
    return list(reversed([_to_out(d) for d in docs]))
