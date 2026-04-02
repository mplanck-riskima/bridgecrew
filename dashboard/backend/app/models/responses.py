"""API response wrappers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class PaginatedResponse(BaseModel):
    """Generic paginated list response."""

    items: list[Any]
    total: int
    page: int = 1
    page_size: int = 50


class CostSummary(BaseModel):
    """Aggregated cost breakdown."""

    total_usd: float = 0.0
    by_agent: dict[str, float] = {}
    by_project: dict[str, float] = {}
    by_model: dict[str, float] = {}


class ActiveTask(BaseModel):
    """A task currently queued or running for an agent."""

    task_id: str
    title: str
    feature_id: str
    feature_title: str
    status: str  # pending | assigned | in_progress


class AgentSummary(BaseModel):
    """Agent with status info."""

    persona_name: str
    model: str
    enabled: bool = True
    status: str = "idle"  # "idle" | "busy"
    current_task: str | None = None
    total_cost_usd: float = 0.0
    active_tasks: list[ActiveTask] = []
