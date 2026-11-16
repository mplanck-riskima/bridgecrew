"""Health watchdog for the bridgecrew Discord bot.

Polls GET http://127.0.0.1:{HEALTH_PORT}/health every HEALTH_CHECK_INTERVAL seconds.
On failure: sends a Discord REST notification, kills the bot process by PID, then
waits HEALTH_RESTART_GRACE seconds before resuming checks. The startup.sh restart
loop then brings the bot back automatically.

Environment variables (all have defaults except the Discord ones):
    HEALTH_PORT              Port for the bot's health endpoint  (default: 8766)
    HEALTH_CHECK_INTERVAL    Seconds between health polls        (default: 600)
    HEALTH_RESTART_GRACE     Seconds to skip checks after kill   (default: 120)
    DISCORD_TOKEN            Bot token for REST notification     (required for alerts)
    DISCORD_CHANNEL_ID       Main channel ID to notify           (required for alerts)
"""
import asyncio
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

import aiohttp

log = logging.getLogger("watchdog")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] watchdog: %(message)s",
)

_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_PID_FILE = str(_SCRIPT_DIR / ".claude-bot" / "bot.pid")
_DEFAULT_FEATURE_MCP_PID_FILE = str(_SCRIPT_DIR / ".claude-bot" / "feature-mcp.pid")
_FEATURE_MCP_START_SCRIPT = str(_SCRIPT_DIR / "feature-mcp" / "start.sh")


# ── Testable helpers ──────────────────────────────────────────────────────────

def kill_bot_process(pid_file: str = _DEFAULT_PID_FILE) -> None:
    """Kill the bot process identified by the PID file.

    Handles missing files, unreadable content, and stale/recycled PIDs
    without raising — logs a warning instead.
    """
    path = Path(pid_file)
    if not path.exists():
        log.warning("PID file %s not found — bot may have already crashed.", pid_file)
        return

    try:
        pid = int(path.read_text().strip())
    except (ValueError, OSError) as exc:
        log.warning("Could not read PID from %s: %s", pid_file, exc)
        return

    log.info("Killing bot process PID %d...", pid)
    try:
        if sys.platform == "win32":
            result = subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            if result.returncode != 0:
                log.warning(
                    "taskkill /PID %d returned %d (may have already exited).", pid, result.returncode
                )
            else:
                log.info("Bot process killed.")
        else:
            _sigkill = getattr(signal, "SIGKILL", 9)  # SIGKILL not defined on Windows
            os.kill(pid, _sigkill)
            log.info("Bot process killed.")
    except (ProcessLookupError, OSError) as exc:
        log.warning("Could not kill PID %d: %s (may have already exited).", pid, exc)


async def check_feature_mcp_health(port: int = 8765) -> bool:
    """Return True if feature-mcp GET /health returns 200."""
    url = f"http://127.0.0.1:{port}/health"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return resp.status == 200
    except Exception as exc:
        log.debug("Feature MCP health check failed: %s", exc)
        return False


def restart_feature_mcp(pid_file: str = _DEFAULT_FEATURE_MCP_PID_FILE) -> None:
    """Kill the existing feature-mcp process (if any) and respawn start.sh."""
    path = Path(pid_file)
    if path.exists():
        try:
            pid = int(path.read_text().strip())
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            else:
                os.kill(pid, getattr(signal, "SIGKILL", 9))
        except (ValueError, OSError, ProcessLookupError):
            pass
        path.unlink(missing_ok=True)

    start_script = Path(_FEATURE_MCP_START_SCRIPT)
    if not start_script.exists():
        log.error("Feature MCP start script not found at %s — cannot restart.", start_script)
        return

    proc = subprocess.Popen(["bash", str(start_script)])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(proc.pid))
    log.info("Feature MCP restarted (PID %d).", proc.pid)


async def check_health(port: int = 8766) -> bool:
    """Return True if GET /health returns 200, False on any error or non-200."""
    url = f"http://127.0.0.1:{port}/health"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return resp.status == 200
    except Exception as exc:
        log.debug("Health check failed: %s", exc)
        return False


async def send_discord_notification(token: str, channel_id: str, message: str) -> None:
    """POST a plain-text message to the Discord channel via the REST API."""
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={"content": message}, headers=headers) as resp:
                if resp.status not in (200, 201):
                    log.warning("Discord notification returned HTTP %d.", resp.status)
                else:
                    log.info("Discord notification sent.")
    except Exception as exc:
        log.error("Failed to send Discord notification: %s", exc)


# ── Main watchdog loop ────────────────────────────────────────────────────────

async def run_watchdog() -> None:
    port = int(os.getenv("HEALTH_PORT", "8766"))
    fmcp_port = int(os.getenv("FEATURE_MCP_PORT", "8765"))
    interval = int(os.getenv("HEALTH_CHECK_INTERVAL", "600"))
    grace = int(os.getenv("HEALTH_RESTART_GRACE", "120"))
    token = os.getenv("DISCORD_TOKEN", "")
    channel_id = os.getenv("DISCORD_CHANNEL_ID", "")

    if not token or not channel_id:
        log.warning(
            "DISCORD_TOKEN or DISCORD_CHANNEL_ID not set — "
            "Discord notifications will be skipped on restart."
        )

    log.info(
        "Watchdog started. Polling bot :%d and feature-mcp :%d every %ds (grace %ds).",
        port, fmcp_port, interval, grace,
    )

    while True:
        await asyncio.sleep(interval)

        # ── Feature MCP ───────────────────────────────────────────────────────
        fmcp_healthy = await check_feature_mcp_health(port=fmcp_port)
        if not fmcp_healthy:
            log.warning("Feature MCP health check FAILED — restarting.")
            if token and channel_id:
                await send_discord_notification(
                    token=token,
                    channel_id=channel_id,
                    message="⚠️ **feature-mcp restarted** — it was unresponsive and has been automatically restarted.",
                )
            restart_feature_mcp()
        else:
            log.info("Feature MCP health check passed.")

        # ── Bot ───────────────────────────────────────────────────────────────
        healthy = await check_health(port=port)
        if healthy:
            log.info("Bot health check passed.")
            continue

        log.warning("Bot health check FAILED — triggering hard reboot.")

        if token and channel_id:
            await send_discord_notification(
                token=token,
                channel_id=channel_id,
                message=(
                    "⚠️ **Hard reboot triggered** — bridgecrew was unresponsive "
                    "and has been automatically restarted."
                ),
            )

        kill_bot_process()

        log.info("Grace period: pausing health checks for %ds.", grace)
        await asyncio.sleep(grace)
        log.info("Grace period over — resuming health checks.")


if __name__ == "__main__":
    asyncio.run(run_watchdog())
