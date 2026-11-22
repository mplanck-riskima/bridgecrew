#!/usr/bin/env python3
"""Stdio MCP server for managing BridgeCrew scheduled orders."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

_env = Path(__file__).parent / ".env"
if _env.exists():
    load_dotenv(_env)

_API_URL = os.environ.get("BRIDGECREW_API_URL", "").rstrip("/")
_API_KEY = os.environ.get("BRIDGECREW_API_KEY", "")


def _api(method: str, path: str, **kwargs) -> Any:
    """Synchronous HTTP call to dashboard API. Raises on HTTP error."""
    with httpx.Client(timeout=10) as c:
        resp = getattr(c, method)(
            f"{_API_URL}{path}",
            headers={"Authorization": f"Bearer {_API_KEY}", "Content-Type": "application/json"},
            **kwargs,
        )
        resp.raise_for_status()
        return None if resp.status_code == 204 else resp.json()


mcp = FastMCP("orders-mcp")


@mcp.tool()
def list_orders() -> list[dict]:
    """Return all scheduled orders."""
    return _api("get", "/api/orders") or []


@mcp.tool()
def create_order(
    name: str,
    prompt: str,
    cron_expr: str,
    project_id: str = "",
    discord_channel_id: str = "",
    prompt_template_id: str = "",
    feature_name: str = "",
    enabled: bool = True,
) -> dict:
    """Create a new scheduled order.

    Call list_projects() and list_personas() first to look up IDs.
    cron_expr must be a 5-field cron expression (minute hour day month weekday).
    If discord_channel_id is omitted, the order fires on the bot's default channel.
    feature_name targets a specific feature session for this order.
    """
    return _api("post", "/api/orders", json={
        "name": name, "prompt": prompt, "cron_expr": cron_expr,
        "project_id": project_id, "discord_channel_id": discord_channel_id,
        "prompt_template_id": prompt_template_id,
        "feature_name": feature_name, "enabled": enabled,
    })


@mcp.tool()
def delete_order(order_id: str) -> dict:
    """Delete a scheduled order by its ID.

    Call this from within a running order to self-cancel it.
    Returns 404 error if the order ID is not found.
    """
    _api("delete", f"/api/orders/{order_id}")
    return {"deleted": True, "order_id": order_id}


@mcp.tool()
def list_projects() -> list[dict]:
    """Return all projects with project_id, name, and discord_channel_id."""
    projects = _api("get", "/api/projects") or []
    return [
        {"project_id": p["project_id"], "name": p["name"],
         "discord_channel_id": p.get("discord_channel_id", "")}
        for p in projects
    ]


@mcp.tool()
def list_personas() -> list[dict]:
    """Return all prompt templates (personas) with id and name."""
    templates = _api("get", "/api/prompts") or []
    return [{"id": t["id"], "name": t["name"]} for t in templates]


if __name__ == "__main__":
    mcp.run()  # stdio transport
