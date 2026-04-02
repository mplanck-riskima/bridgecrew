"""Project and related models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field
from ulid import ULID


def _now() -> datetime:
    return datetime.now(UTC)


def _ulid() -> str:
    return str(ULID())


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class Project(BaseModel):
    """A project grouping multiple features."""

    project_id: str = Field(default_factory=_ulid)
    name: str
    description: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
