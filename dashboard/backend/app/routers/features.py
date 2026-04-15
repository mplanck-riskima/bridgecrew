"""Feature list, detail, and bot-reporting endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from pymongo import DESCENDING
from pymongo.errors import DuplicateKeyError
from ulid import ULID

from app.db import features_col
from app.middleware.api_key import require_api_key

router = APIRouter(tags=["features"])


class FeatureCreate(BaseModel):
    """Payload the discord-Claude bot sends when starting a feature."""
    feature_id: str = ""
    project_id: str
    name: str
    description: str = ""
    session_id: str = ""
    prompt_template_id: str = ""
    subdir: str = ""


class FeatureUpdate(BaseModel):
    """Payload the discord-Claude bot sends when updating / completing a feature."""
    status: str | None = None
    summary: str | None = None
    total_cost_usd: float | None = None
    git_branch: str | None = None
    session_id: str | None = None
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    markdown_content: str | None = None


@router.get("/features")
def list_features(
    status: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, le=200),
) -> dict:
    """List features, optionally filtered by status or project."""
    query: dict = {}
    if status:
        query["status"] = status
    if project_id:
        query["project_id"] = project_id

    total = features_col().count_documents(query)
    skip = (page - 1) * page_size
    docs = (
        features_col()
        .find(query, {"_id": 0})
        .sort("created_at", DESCENDING)
        .skip(skip)
        .limit(page_size)
    )

    return {"items": list(docs), "total": total, "page": page, "page_size": page_size}


@router.get("/features/{feature_id}")
def get_feature(feature_id: str) -> dict:
    """Return a single feature with its tasks."""
    doc = features_col().find_one({"feature_id": feature_id}, {"_id": 0})
    if doc is None:
        raise HTTPException(status_code=404, detail="Feature not found")
    return doc


@router.delete("/features/{feature_id}")
def delete_feature(feature_id: str) -> dict:
    """Permanently delete a feature."""
    result = features_col().delete_one({"feature_id": feature_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Feature not found")
    return {"status": "deleted", "feature_id": feature_id}


@router.post("/features", status_code=201)
def create_feature(
    body: FeatureCreate,
    _: None = Depends(require_api_key),
) -> dict:
    """Create a feature record (called by the discord-Claude bot on /start-feature)."""
    doc = {
        "feature_id": body.feature_id or str(ULID()),
        "project_id": body.project_id,
        "name": body.name,
        "description": body.description,
        "status": "active",
        "session_id": body.session_id,
        "prompt_template_id": body.prompt_template_id,
        "subdir": body.subdir,
        "total_cost_usd": 0.0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "summary": None,
        "git_branch": None,
        "created_at": datetime.now(UTC),
        "completed_at": None,
    }
    try:
        features_col().insert_one(doc)
        doc.pop("_id", None)
        return doc
    except DuplicateKeyError:
        existing = features_col().find_one({"feature_id": doc["feature_id"]}, {"_id": 0})
        return existing


@router.patch("/features/{feature_id}")
def update_feature(
    feature_id: str,
    body: FeatureUpdate,
    _: None = Depends(require_api_key),
) -> dict:
    """Update a feature (called by the discord-Claude bot on completion / cost accumulation)."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    if updates.get("status") == "completed" and "completed_at" not in updates:
        updates["completed_at"] = datetime.now(UTC)

    result = features_col().update_one({"feature_id": feature_id}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Feature not found")

    doc = features_col().find_one({"feature_id": feature_id}, {"_id": 0})
    return doc
