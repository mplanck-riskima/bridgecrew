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
    status == "active" only when the session_id is completely unknown to the
    MCP server (e.g. bot restart assigned a new session ID). If the session
    is known but completed, the feature was properly closed — no fallback.
    """
    features = await get_features(project_dir)
    # 1. Exact session match (active session)
    for feat in features:
        for sess in feat.get("sessions", []):
            if sess.get("session_id") == session_id and sess.get("status") == "active":
                return feat
    # 2. If session_id is known to any feature (even completed), don't fall back —
    #    the session was properly closed out.
    for feat in features:
        for sess in feat.get("sessions", []):
            if sess.get("session_id") == session_id:
                return None
    # 3. Session is completely unknown (bot restart / new session ID) —
    #    fall back to any feature that is still marked active.
    for feat in features:
        if feat.get("status") == "active":
            return feat
    return None


async def restart_server() -> None:
    """Tell the feature-mcp server to restart (POST /admin/restart)."""
    url = f"{MCP_BASE}/api/admin/restart"
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.post(url)
        except httpx.RemoteProtocolError:
            # Server exits mid-response — that's expected on restart
            pass
        except Exception as exc:
            logger.warning("feature-mcp restart failed: %s", exc)


async def complete_feature(
    project_dir: Path,
    session_id: str,
    summary: str = "",
) -> bool:
    """Mark the active feature as completed via the REST API.

    Safe to call even if Claude already called feature_complete via MCP — if the
    session has already been unregistered the server returns a non-200 status and
    we ignore it.  Returns True if the server confirmed completion.
    """
    url = f"{MCP_BASE}/api/projects/{_encode(project_dir)}/sessions/{session_id}/complete"
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.post(url, json={"summary": summary})
            return r.status_code == 200
        except Exception as exc:
            logger.warning("feature-mcp complete_feature failed: %s", exc)
            return False


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


async def abandon_feature_sessions(project_dir: Path, feature_name: str) -> bool:
    """Abandon all active sessions for a feature. Returns True on success."""
    url = f"{MCP_BASE}/api/projects/{_encode(project_dir)}/features/{feature_name}/abandon-sessions"
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.post(url)
            return r.status_code == 200
        except Exception as exc:
            logger.warning("feature-mcp abandon_feature_sessions failed: %s", exc)
            return False
