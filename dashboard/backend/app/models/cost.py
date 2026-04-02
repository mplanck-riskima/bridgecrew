"""Cost log entry model."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


class CostLogEntry(BaseModel):
    """A single cost event logged after an agent completes a task."""

    task_id: str
    feature_id: str = ""
    project_id: str = ""
    agent: str
    model: str = ""
    category: str = ""
    cost_usd: float = 0.0
    started_at: datetime = Field(default_factory=_now)
    completed_at: datetime = Field(default_factory=_now)
