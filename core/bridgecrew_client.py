"""
HTTP client for the BridgeCrew dashboard API.

The discord-Claude bot calls this to:
  1. Fetch the assigned persona for a project before starting a session
  2. Report feature lifecycle events (start / complete)
  3. Report session costs after each Claude run
  4. Report activity (user messages + Claude responses) for the 24-hour feed

All calls use Bearer-token auth (BRIDGECREW_API_KEY env var).
If BRIDGECREW_API_URL is not set the client is disabled and all calls are no-ops.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)

_API_URL = os.environ.get("BRIDGECREW_API_URL", "").rstrip("/")
_API_KEY = os.environ.get("BRIDGECREW_API_KEY", "")

if _API_URL and _API_KEY:
    log.info("BridgeCrew integration enabled: %s", _API_URL)
else:
    log.info("BridgeCrew integration disabled (BRIDGECREW_API_URL/KEY not set) — tracking is a no-op")


def _enabled() -> bool:
    return bool(_API_URL and _API_KEY)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
    }


def get_project_prompt(project_id: str) -> tuple[str, str]:
    """
    Return (content, name) for the persona assigned to a project.
    Returns ("", "") if not configured or on any error.
    """
    if not _enabled() or not project_id:
        return "", ""
    try:
        resp = httpx.get(
            f"{_API_URL}/api/projects/{project_id}/prompt",
            headers=_headers(),
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("content", ""), data.get("name") or ""
        log.warning("get_project_prompt: HTTP %s for project %s", resp.status_code, project_id)
    except Exception as exc:
        log.warning("get_project_prompt failed: %s", exc)
    return "", ""


def report_feature_started(
    project_id: str,
    feature_name: str,
    session_id: str,
    feature_id: str = "",
    prompt_template_id: str = "",
    subdir: str = "",
) -> str | None:
    """
    Tell the BridgeCrew dashboard a feature has started. Returns the feature_id
    assigned by the server, or None on failure.
    """
    if not _enabled():
        return None
    payload = {
        "feature_id": feature_id,
        "project_id": project_id,
        "name": feature_name,
        "session_id": session_id,
        "prompt_template_id": prompt_template_id,
        "subdir": subdir or "",
    }
    try:
        resp = httpx.post(
            f"{_API_URL}/api/features",
            headers=_headers(),
            json=payload,
            timeout=5,
        )
        if resp.status_code == 201:
            return resp.json().get("feature_id")
        log.warning("report_feature_started: HTTP %s", resp.status_code)
    except Exception as exc:
        log.warning("report_feature_started failed: %s", exc)
    return None


def report_feature_completed(
    feature_id: str,
    summary: str = "",
    total_cost_usd: float = 0.0,
    git_branch: str = "",
    total_input_tokens: int = 0,
    total_output_tokens: int = 0,
    markdown_content: str | None = None,
) -> None:
    """Tell the BridgeCrew dashboard a feature has been completed."""
    if not _enabled() or not feature_id:
        return
    payload: dict = {"status": "completed"}
    if summary:
        payload["summary"] = summary
    if total_cost_usd:
        payload["total_cost_usd"] = total_cost_usd
    if git_branch:
        payload["git_branch"] = git_branch
    if total_input_tokens:
        payload["total_input_tokens"] = total_input_tokens
    if total_output_tokens:
        payload["total_output_tokens"] = total_output_tokens
    if markdown_content is not None:
        payload["markdown_content"] = markdown_content
    try:
        resp = httpx.patch(
            f"{_API_URL}/api/features/{feature_id}",
            headers=_headers(),
            json=payload,
            timeout=5,
        )
        if resp.status_code != 200:
            log.warning("report_feature_completed: HTTP %s", resp.status_code)
    except Exception as exc:
        log.warning("report_feature_completed failed: %s", exc)


def report_activity(
    project_id: str,
    role: str,
    author: str,
    content: str,
    feature_name: str | None = None,
) -> None:
    """Log a user message or Claude response to the 24-hour activity feed."""
    if not _enabled() or not project_id:
        return
    payload = {
        "project_id": project_id,
        "role": role,
        "author": author,
        "content": content[:2000],
        "feature_name": feature_name,
    }
    try:
        resp = httpx.post(
            f"{_API_URL}/api/activity",
            headers=_headers(),
            json=payload,
            timeout=5,
        )
        if resp.status_code != 201:
            log.warning("report_activity: HTTP %s", resp.status_code)
    except Exception as exc:
        log.warning("report_activity failed: %s", exc)


def get_projects() -> list[dict]:
    """Fetch all projects from the dashboard."""
    if not _enabled():
        return []
    try:
        resp = httpx.get(f"{_API_URL}/api/projects", headers=_headers(), timeout=5)
        if resp.status_code == 200:
            return resp.json()
        log.warning("get_projects: HTTP %s", resp.status_code)
    except Exception as exc:
        log.warning("get_projects failed: %s", exc)
    return []


def create_project(name: str, description: str = "") -> str | None:
    """Create a project in the dashboard. Returns project_id or None."""
    if not _enabled():
        return None
    try:
        resp = httpx.post(
            f"{_API_URL}/api/projects",
            headers=_headers(),
            json={"name": name, "description": description},
            timeout=5,
        )
        if resp.status_code == 201:
            return resp.json().get("project_id")
        log.warning("create_project: HTTP %s", resp.status_code)
    except Exception as exc:
        log.warning("create_project failed: %s", exc)
    return None


def get_prompt_by_id(template_id: str) -> tuple[str, str]:
    """Return (content, name) for a specific prompt template by its MongoDB ObjectId.
    Returns ("", "") if not found or on any error.
    """
    if not _enabled() or not template_id:
        return "", ""
    try:
        resp = httpx.get(
            f"{_API_URL}/api/prompts/{template_id}",
            headers=_headers(),
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("content", ""), data.get("name") or ""
        log.warning("get_prompt_by_id: HTTP %s for template %s", resp.status_code, template_id)
    except Exception as exc:
        log.warning("get_prompt_by_id failed: %s", exc)
    return "", ""


def list_prompts() -> list[dict]:
    """Fetch all prompt templates (personas) from the dashboard API."""
    if not _enabled():
        return []
    try:
        resp = httpx.get(f"{_API_URL}/api/prompts", headers=_headers(), timeout=5)
        if resp.status_code == 200:
            return resp.json()
        log.warning("list_prompts: HTTP %s", resp.status_code)
    except Exception as exc:
        log.warning("list_prompts failed: %s", exc)
    return []


def assign_project_persona(project_id: str, prompt_template_id: str | None) -> bool:
    """Assign (or clear) a persona for a project via PUT /api/projects/{id}."""
    if not _enabled() or not project_id:
        return False
    payload = {"prompt_template_id": prompt_template_id or ""}
    try:
        resp = httpx.put(
            f"{_API_URL}/api/projects/{project_id}",
            headers=_headers(),
            json=payload,
            timeout=5,
        )
        if resp.status_code == 200:
            return True
        log.warning("assign_project_persona: HTTP %s", resp.status_code)
    except Exception as exc:
        log.warning("assign_project_persona failed: %s", exc)
    return False


def report_cost(
    project_id: str,
    session_id: str,
    model: str,
    cost_usd: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    feature_id: str = "",
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> None:
    """Report a session cost entry to the BridgeCrew dashboard."""
    if not _enabled() or cost_usd <= 0:
        return
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "project_id": project_id,
        "feature_id": feature_id,
        "session_id": session_id,
        "model": model,
        "cost_usd": cost_usd,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "started_at": started_at.isoformat() if started_at else now,
        "completed_at": completed_at.isoformat() if completed_at else now,
    }
    try:
        resp = httpx.post(
            f"{_API_URL}/api/costs",
            headers=_headers(),
            json=payload,
            timeout=5,
        )
        if resp.status_code != 201:
            log.warning("report_cost: HTTP %s", resp.status_code)
    except Exception as exc:
        log.warning("report_cost failed: %s", exc)
