"""Lightweight aiohttp health endpoint for the Discord bot.

Exposes GET /health on 127.0.0.1:{HEALTH_PORT}:
  200 {"status": "ok"}         — bot.is_ready() and not bot.is_closed()
  503 {"status": "unhealthy"}  — otherwise

Usage:
    await start_health_server(bot)   # call from setup_hook()
    await stop_health_server()       # call from close()
"""
import logging
import os

from aiohttp import web

log = logging.getLogger(__name__)

_runner: web.AppRunner | None = None
_bot = None


async def start_health_server(bot, port: int | None = None) -> None:
    """Start the health HTTP server. Safe to call even if port is already held."""
    global _runner, _bot

    # Stop any previously running server (idempotent startup).
    if _runner is not None:
        await stop_health_server()

    _bot = bot
    port = port or int(os.getenv("HEALTH_PORT", "8766"))

    app = web.Application()
    app.router.add_get("/health", _handle_health)

    # Default shutdown_timeout is 60s; open keep-alive connections (e.g. the
    # watchdog) would otherwise stall bot shutdown/restart for that long.
    _runner = web.AppRunner(app, shutdown_timeout=1.0)
    await _runner.setup()

    site = web.TCPSite(_runner, "127.0.0.1", port)
    try:
        await site.start()
        log.info("Health server listening on 127.0.0.1:%d", port)
    except OSError as exc:
        log.warning(
            "Health server could not bind to port %d: %s — "
            "watchdog will never receive 200; investigate port conflict.",
            port, exc,
        )


async def stop_health_server() -> None:
    """Gracefully stop the health server. Safe to call when not started."""
    global _runner, _bot
    if _runner is not None:
        await _runner.cleanup()
        _runner = None
        _bot = None
        log.info("Health server stopped.")


async def _handle_health(request: web.Request) -> web.Response:
    if _bot is not None and _bot.is_ready() and not _bot.is_closed():
        return web.json_response({"status": "ok"})
    return web.json_response({"status": "unhealthy"}, status=503)
