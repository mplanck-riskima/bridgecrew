"""Prompt template CRUD endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db import prompt_templates_col
from app.middleware.api_key import require_api_key

router = APIRouter(tags=["prompts"])


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


class PromptCreate(BaseModel):
    name: str
    description: str = ""
    content: str


class PromptUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None


@router.get("/prompts")
def list_prompts() -> list[dict]:
    """Return all prompt templates."""
    return [_serialize(doc) for doc in prompt_templates_col().find()]


@router.post("/prompts", status_code=201)
def create_prompt(body: PromptCreate) -> dict:
    """Create a new prompt template."""
    doc = {
        "name": body.name,
        "description": body.description,
        "content": body.content,
        "updated_at": datetime.now(UTC),
    }
    result = prompt_templates_col().insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    return doc


@router.get("/prompts/{prompt_id}")
def get_prompt(prompt_id: str, _: None = Depends(require_api_key)) -> dict:
    """Return a single prompt template (bot-facing, requires API key)."""
    try:
        oid = ObjectId(prompt_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid prompt ID")
    doc = prompt_templates_col().find_one({"_id": oid})
    if doc is None:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return _serialize(doc)


@router.put("/prompts/{prompt_id}")
def update_prompt(prompt_id: str, body: PromptUpdate) -> dict:
    """Update a prompt template."""
    try:
        oid = ObjectId(prompt_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid prompt ID")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updates["updated_at"] = datetime.now(UTC)

    result = prompt_templates_col().update_one({"_id": oid}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Prompt not found")

    return get_prompt(prompt_id)


@router.delete("/prompts/{prompt_id}", status_code=204)
def delete_prompt(prompt_id: str) -> None:
    """Delete a prompt template."""
    try:
        oid = ObjectId(prompt_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid prompt ID")
    result = prompt_templates_col().delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Prompt not found")
