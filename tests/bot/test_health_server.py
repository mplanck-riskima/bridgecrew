"""Tests for the aiohttp health endpoint."""
import aiohttp
import pytest
from unittest.mock import MagicMock


async def test_health_200_when_bot_ready():
    """Returns 200 {"status": "ok"} when bot is ready and not closed."""
    from core.health_server import start_health_server, stop_health_server

    bot = MagicMock()
    bot.is_ready.return_value = True
    bot.is_closed.return_value = False

    await start_health_server(bot, port=18766)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://127.0.0.1:18766/health") as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "ok"
    finally:
        await stop_health_server()


async def test_health_503_when_bot_not_ready():
    """Returns 503 {"status": "unhealthy"} when bot.is_ready() is False."""
    from core.health_server import start_health_server, stop_health_server

    bot = MagicMock()
    bot.is_ready.return_value = False
    bot.is_closed.return_value = False

    await start_health_server(bot, port=18767)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://127.0.0.1:18767/health") as resp:
                assert resp.status == 503
                data = await resp.json()
                assert data["status"] == "unhealthy"
    finally:
        await stop_health_server()


async def test_health_503_when_bot_closed():
    """Returns 503 when bot.is_closed() is True, even if is_ready() is True."""
    from core.health_server import start_health_server, stop_health_server

    bot = MagicMock()
    bot.is_ready.return_value = True
    bot.is_closed.return_value = True

    await start_health_server(bot, port=18768)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://127.0.0.1:18768/health") as resp:
                assert resp.status == 503
    finally:
        await stop_health_server()


async def test_stop_health_server_idempotent():
    """Calling stop_health_server() twice does not raise."""
    from core.health_server import start_health_server, stop_health_server

    bot = MagicMock()
    bot.is_ready.return_value = True
    bot.is_closed.return_value = False

    await start_health_server(bot, port=18769)
    await stop_health_server()
    await stop_health_server()  # must not raise


async def test_start_health_server_port_in_use(caplog):
    """OSError on bind is caught and logged; no exception propagates."""
    import logging
    import socket
    from core.health_server import start_health_server, stop_health_server

    bot = MagicMock()
    bot.is_ready.return_value = True
    bot.is_closed.return_value = False

    # Hold port 18770 with a raw socket so the health server can't bind it.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 18770))
    sock.listen(1)
    try:
        with caplog.at_level(logging.WARNING, logger="core.health_server"):
            await start_health_server(bot, port=18770)  # port already held — OSError expected
        assert any("port" in r.message.lower() or "bind" in r.message.lower()
                   for r in caplog.records)
    finally:
        sock.close()
        await stop_health_server()
