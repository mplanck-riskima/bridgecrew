# core/mcp_client.py
"""Async HTTP client for the feature-mcp server (http://localhost:8765)."""
import logging
from pathlib import Path
from urllib.parse import quote

import httpx

MCP_BASE = "http://localhost:8765"
logger = logging.getLogger(__name__)


def _encode(project_dir: Path | str) -> str:
    return quote(str(project_dir), safe="")


async def get_features(project_dir: Path) -> list[dict]:
    """List all features for the project."""
    url = f"{MCP_BASE}/api/projects/{_encode(project_dir)}/features"
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            logger.warning("feature-mcp get_features failed: %s", exc)
            return []


async def get_session_feature(project_dir: Path, session_id: str) -> dict | None:
    """Return the active feature for this session, or None.

    First tries to match by session_id; falls back to any feature with
    status == "active" so the gate doesn't fire when the session ID has
    changed (e.g. bot restart) but a feature is still active.
    """
    features = await get_features(project_dir)
    # 1. Exact session match
    for feat in features:
        for sess in feat.get("sessions", []):
            if sess.get("session_id") == session_id and sess.get("status") == "active":
                return feat
    # 2. Fallback: any feature that is still marked active
    for feat in features:
        if feat.get("status") == "active":
            return feat
    return None


async def post_cost(
    project_dir: Path,
    session_id: str,
    cost_usd: float,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Push token/cost data to the MCP server after a streaming response."""
    url = f"{MCP_BASE}/api/projects/{_encode(project_dir)}/sessions/{session_id}/cost"
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.post(url, json={
                "cost_usd": cost_usd,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            })
        except Exception as exc:
            logger.warning("feature-mcp post_cost failed: %s", exc)
