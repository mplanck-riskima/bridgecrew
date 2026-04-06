"""Project CRUD endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pymongo import DESCENDING
from ulid import ULID

from bson import ObjectId

from app.db import cost_log_col, features_col, prompt_templates_col, projects_col
from app.middleware.api_key import require_api_key

router = APIRouter(tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    prompt_template_id: str | None = None


@router.get("/projects")
def list_projects() -> list[dict]:
    """Return all projects with feature counts."""
    projects = list(projects_col().find(
        {"status": {"$ne": "archived"}},
        {"_id": 0},
    ).sort("created_at", DESCENDING))

    # Build a map of project_id -> feature count.
    count_pipeline = [
        {"$match": {"project_id": {"$ne": ""}}},
        {"$group": {"_id": "$project_id", "count": {"$sum": 1}}},
    ]
    counts = {
        doc["_id"]: doc["count"]
        for doc in features_col().aggregate(count_pipeline)
    }

    for project in projects:
        project["feature_count"] = counts.get(project.get("project_id", ""), 0)

    return projects


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate) -> dict:
    """Create a new project."""
    doc = {
        "project_id": str(ULID()),
        "name": body.name,
        "description": body.description,
        "status": "active",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    projects_col().insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/projects/{project_id}")
def get_project(project_id: str) -> dict:
    """Return a project with its features and cost summary."""
    doc = projects_col().find_one({"project_id": project_id}, {"_id": 0})
    if doc is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Attach features
    doc["features"] = list(
        features_col()
        .find({"project_id": project_id}, {"_id": 0})
        .sort("created_at", DESCENDING)
    )

    # Attach cost summary
    cost_pipeline = [
        {"$match": {"project_id": project_id}},
        {"$group": {"_id": None, "total": {"$sum": "$cost_usd"}}},
    ]
    cost_result = list(cost_log_col().aggregate(cost_pipeline))
    doc["total_cost_usd"] = cost_result[0]["total"] if cost_result else 0.0

    return doc


@router.put("/projects/{project_id}")
def update_project(project_id: str, body: ProjectUpdate) -> dict:
    """Update a project."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates["updated_at"] = datetime.now(UTC)
    result = projects_col().update_one(
        {"project_id": project_id},
        {"$set": updates},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Project not found")

    return get_project(project_id)


@router.delete("/projects/{project_id}")
def delete_project(project_id: str) -> dict:
    """Delete a project."""
    result = projects_col().delete_one({"project_id": project_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "deleted", "project_id": project_id}


@router.get("/projects/{project_id}/prompt")
def get_project_prompt(
    project_id: str,
    _: None = Depends(require_api_key),
) -> dict:
    """Return the assigned prompt template content for a project (bot-facing, requires API key)."""
    project = projects_col().find_one({"project_id": project_id}, {"_id": 0})
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    template_id = project.get("prompt_template_id")
    if not template_id:
        return {"content": "", "name": None, "id": None}

    try:
        oid = ObjectId(template_id)
    except Exception:
        return {"content": "", "name": None, "id": None}

    template = prompt_templates_col().find_one({"_id": oid})
    if template is None:
        return {"content": "", "name": None, "id": None}

    return {
        "id": str(template["_id"]),
        "name": template.get("name"),
        "content": template.get("content", ""),
    }
