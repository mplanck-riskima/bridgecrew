"""Tests for the health watchdog process."""
import asyncio
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


def test_kill_bot_process_windows_already_exited(wdog, tmp_path, caplog):
    """On Windows, logs a warning when taskkill returns non-zero (bot already gone)."""
    import logging
    pid_file = tmp_path / "bot.pid"
    pid_file.write_text("9999")

    mock_result = MagicMock()
    mock_result.returncode = 128  # taskkill returns 128 for "process not found"

    with patch("subprocess.run", return_value=mock_result) as mock_run, \
         patch.object(sys, "platform", "win32"), \
         caplog.at_level(logging.WARNING):
        wdog.kill_bot_process(str(pid_file))  # must not raise

    mock_run.assert_called_once_with(
        ["taskkill", "/F", "/PID", "9999"], capture_output=True
    )
    assert caplog.records, "Expected a warning log for non-zero taskkill exit"


# ── run_watchdog loop ─────────────────────────────────────────────────────────

async def test_run_watchdog_triggers_restart_on_unhealthy(wdog):
    """run_watchdog calls send_discord_notification and kill_bot_process on failure."""
    import asyncio

    sleep_calls = []

    async def fake_sleep(n):
        sleep_calls.append(n)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError("test stop")

    with patch.object(wdog, "check_health", new=AsyncMock(return_value=False)), \
         patch.object(wdog, "send_discord_notification", new=AsyncMock()) as mock_notify, \
         patch.object(wdog, "kill_bot_process") as mock_kill, \
         patch("asyncio.sleep", side_effect=fake_sleep), \
         patch.dict(os.environ, {"DISCORD_TOKEN": "tok", "DISCORD_CHANNEL_ID": "123",
                                  "HEALTH_CHECK_INTERVAL": "1", "HEALTH_RESTART_GRACE": "1"}):
        with pytest.raises(asyncio.CancelledError):
            await wdog.run_watchdog()

    mock_notify.assert_awaited_once()
    mock_kill.assert_called_once()


async def test_run_watchdog_no_restart_when_healthy(wdog):
    """run_watchdog does not kill or notify when health check passes."""
    import asyncio

    sleep_calls = []

    async def fake_sleep(n):
        sleep_calls.append(n)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError("test stop")

    with patch.object(wdog, "check_health", new=AsyncMock(return_value=True)), \
         patch.object(wdog, "send_discord_notification", new=AsyncMock()) as mock_notify, \
         patch.object(wdog, "kill_bot_process") as mock_kill, \
         patch("asyncio.sleep", side_effect=fake_sleep), \
         patch.dict(os.environ, {"DISCORD_TOKEN": "tok", "DISCORD_CHANNEL_ID": "123",
                                  "HEALTH_CHECK_INTERVAL": "1", "HEALTH_RESTART_GRACE": "1"}):
        with pytest.raises(asyncio.CancelledError):
            await wdog.run_watchdog()

    mock_notify.assert_not_awaited()
    mock_kill.assert_not_called()
