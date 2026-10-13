"""Tests for the health watchdog process."""
import importlib.util
import os
import signal
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def load_watchdog():
    """Import watchdog.py without triggering the __main__ block."""
    spec = importlib.util.spec_from_file_location(
        "watchdog_module",
        Path(__file__).parent.parent.parent / "watchdog.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def wdog():
    return load_watchdog()


# ── kill_bot_process ──────────────────────────────────────────────────────────

def test_kill_bot_process_windows(wdog, tmp_path):
    """On Windows, calls taskkill /F /PID with the PID from the file."""
    pid_file = tmp_path / "bot.pid"
    pid_file.write_text("1234")

    with patch("subprocess.run") as mock_run, patch.object(sys, "platform", "win32"):
        wdog.kill_bot_process(str(pid_file))

    mock_run.assert_called_once_with(
        ["taskkill", "/F", "/PID", "1234"], capture_output=True
    )


def test_kill_bot_process_linux(wdog, tmp_path):
    """On Linux, calls os.kill(pid, SIGKILL) with the PID from the file."""
    pid_file = tmp_path / "bot.pid"
    pid_file.write_text("5678")

    with patch("os.kill") as mock_kill, patch.object(sys, "platform", "linux"):
        wdog.kill_bot_process(str(pid_file))

    mock_kill.assert_called_once_with(5678, getattr(signal, "SIGKILL", 9))


def test_kill_bot_process_missing_pidfile(wdog, tmp_path, caplog):
    """Missing PID file logs a warning and does not raise."""
    import logging
    missing = tmp_path / "bot.pid"
    with caplog.at_level(logging.WARNING):
        wdog.kill_bot_process(str(missing))  # must not raise
    assert caplog.records, "Expected a log warning"


def test_kill_bot_process_stale_pid(wdog, tmp_path):
    """ProcessLookupError (stale PID) is caught and does not propagate."""
    pid_file = tmp_path / "bot.pid"
    pid_file.write_text("99999")

    with patch("os.kill", side_effect=ProcessLookupError("no such process")), \
         patch.object(sys, "platform", "linux"):
        wdog.kill_bot_process(str(pid_file))  # must not raise


# ── check_health ─────────────────────────────────────────────────────────────

async def test_check_health_returns_true_on_200(wdog):
    """Returns True when GET /health responds with 200."""
    mock_resp = MagicMock()
    mock_resp.status = 200

    mock_get_cm = AsyncMock()
    mock_get_cm.__aenter__.return_value = mock_resp
    mock_get_cm.__aexit__.return_value = False

    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = False
    # MagicMock so calling .get(...) directly returns the CM (not a coroutine)
    mock_session.get = MagicMock(return_value=mock_get_cm)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await wdog.check_health(port=8766)
    assert result is True


async def test_check_health_returns_false_on_503(wdog):
    """Returns False when GET /health responds with 503."""
    mock_resp = MagicMock()
    mock_resp.status = 503

    mock_get_cm = AsyncMock()
    mock_get_cm.__aenter__.return_value = mock_resp
    mock_get_cm.__aexit__.return_value = False

    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = False
    mock_session.get = MagicMock(return_value=mock_get_cm)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await wdog.check_health(port=8766)
    assert result is False


async def test_check_health_returns_false_on_connection_error(wdog):
    """Returns False on connection refused (bot process dead)."""
    import aiohttp

    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = False
    mock_session.get = MagicMock(side_effect=aiohttp.ClientConnectionError("refused"))

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await wdog.check_health(port=8766)
    assert result is False


# ── send_discord_notification ─────────────────────────────────────────────────

async def test_send_discord_notification_posts_to_correct_url(wdog):
    """POSTs to the correct Discord REST URL with Bot token and message."""
    mock_resp = MagicMock()
    mock_resp.status = 200

    mock_post_cm = AsyncMock()
    mock_post_cm.__aenter__.return_value = mock_resp
    mock_post_cm.__aexit__.return_value = False

    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = False
    mock_session.post = MagicMock(return_value=mock_post_cm)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        await wdog.send_discord_notification(
            token="mytoken",
            channel_id="987654321",
            message="⚠️ Hard reboot triggered",
        )

    call_args = mock_session.post.call_args
    url = call_args[0][0]
    assert "987654321" in url
    assert "discord.com/api" in url
    kwargs = call_args[1]
    assert kwargs["json"]["content"] == "⚠️ Hard reboot triggered"
    assert kwargs["headers"]["Authorization"] == "Bot mytoken"


async def test_send_discord_notification_logs_on_failure(wdog, caplog):
    """Network error during notification is caught; does not propagate."""
    import aiohttp
    import logging

    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = False
    mock_session.post = MagicMock(side_effect=aiohttp.ClientConnectionError("network down"))

    with patch("aiohttp.ClientSession", return_value=mock_session), \
         caplog.at_level(logging.ERROR):
        await wdog.send_discord_notification("tok", "123", "msg")  # must not raise

    assert caplog.records, "Expected an error log"
