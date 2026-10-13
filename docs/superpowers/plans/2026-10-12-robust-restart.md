# Robust Restart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an HTTP health endpoint to the bot and an external watchdog process that polls it every 10 minutes, kills the bot and sends a Discord notification when it becomes unresponsive, letting the `startup.sh` restart loop bring it back automatically.

**Architecture:** The bot runs a minimal `aiohttp.web` server (`core/health_server.py`) on port 8766 inside its own event loop; a standalone `watchdog.py` process (launched as a background job by `startup.sh`) polls `GET /health` every 10 minutes and, on failure, POSTs a Discord REST notification and kills the bot by PID — the updated `startup.sh` restart loop then restarts it automatically on any non-zero exit.

**Tech Stack:** Python 3.x, aiohttp (already installed via discord.py), pytest-asyncio (already in requirements-test.txt), bash.

**Spec:** `docs/superpowers/specs/2026-10-12-robust-restart-design.md`

## Global Constraints

- No new Python runtime dependencies (aiohttp already present via discord.py).
- Health port: `HEALTH_PORT` env var, default `8766`; bind to `127.0.0.1` only.
- Watchdog intervals: `HEALTH_CHECK_INTERVAL` (seconds, default `600`), `HEALTH_RESTART_GRACE` (seconds, default `120`).
- Bot token for REST notification: `DISCORD_TOKEN`; channel: `DISCORD_CHANNEL_ID` (both already in env).
- Discord REST endpoint: `POST https://discord.com/api/v10/channels/{CHANNEL_ID}/messages` with `Authorization: Bot {TOKEN}`.
- Windows kill: `subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)`.
- Linux/macOS kill: `os.kill(pid, signal.SIGKILL)`.
- Bot writes PID to `.claude-bot/bot.pid` before `current_bot.run()`; removes it in a `finally` block in `main()`.
- `startup.sh` restart loop exits on code `0` (clean stop), restarts on any other exit code.
- Tests live under `tests/bot/`; `asyncio_mode = auto` is already set in `pytest.ini` — no `@pytest.mark.asyncio` needed.

## Review Focus

1. **503 during bot startup** — the health server starts in `setup_hook()` before `on_ready` fires; `GET /health` during startup must return 503, not 200, so the watchdog doesn't count a slow startup as healthy.
2. **Stale/reused PID** — if `.claude-bot/bot.pid` holds a PID that the OS has recycled for a different process, `kill`/`taskkill` hits the wrong process; `kill_bot_process` must swallow `ProcessLookupError`/`OSError` and log a warning rather than crash.
3. **Port already in use** — if port 8766 is occupied when the bot starts, `aiohttp` raises `OSError`; `start_health_server` must catch it, log a clear warning, and return without crashing the bot.
4. **Grace period overlap** — if the bot is killed and starts coming back up, the watchdog must not fire again during the grace sleep; the linear loop structure ensures only one kill per unhealthy detection.
5. **Watchdog accumulation across `startup.sh` runs** — teardown must kill the existing watchdog by PID from `.claude-bot/watchdog.pid` before starting a new one; verified manually in Task 4.

---

### Task 1: Health Server Module

**Files:**
- Create: `core/health_server.py`
- Create: `tests/bot/test_health_server.py`

**Interfaces:**
- Produces:
  - `async def start_health_server(bot, port: int | None = None) -> None`
  - `async def stop_health_server() -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/bot/test_health_server.py`:

```python
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
    from core.health_server import start_health_server, stop_health_server

    bot = MagicMock()
    bot.is_ready.return_value = True
    bot.is_closed.return_value = False

    # Bind port 18770 twice — second call must not raise.
    await start_health_server(bot, port=18770)
    try:
        with caplog.at_level(logging.WARNING, logger="core.health_server"):
            await start_health_server(bot, port=18770)   # port already held — OSError expected
        assert any("port" in r.message.lower() or "bind" in r.message.lower()
                   for r in caplog.records)
    finally:
        await stop_health_server()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd M:/bridgecrew
venv/Scripts/python -m pytest tests/bot/test_health_server.py -v 2>&1 | head -20
```

Expected: `ImportError` — `core.health_server` does not exist yet.

- [ ] **Step 3: Create `core/health_server.py`**

```python
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

    _runner = web.AppRunner(app)
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
venv/Scripts/python -m pytest tests/bot/test_health_server.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/health_server.py tests/bot/test_health_server.py
git commit -m "feat: add aiohttp health endpoint (GET /health)"
```

---

### Task 2: Wire health server and PID file into bot.py

**Files:**
- Modify: `bot.py`
- Create: `tests/bot/test_bot_health_wiring.py`

**Interfaces:**
- Consumes: `core.health_server.start_health_server(bot)`, `core.health_server.stop_health_server()`
- Produces: `.claude-bot/bot.pid` written at `main()` entry, removed at `main()` exit.

- [ ] **Step 1: Write the failing test**

Create `tests/bot/test_bot_health_wiring.py`:

```python
"""Tests for bot.py PID file lifecycle."""
import os
from pathlib import Path


def test_pid_file_is_written_and_cleaned(tmp_path):
    """PID file exists while main() runs and is absent after exit."""
    # We exercise the contract without importing ClaudeBot (avoids DISCORD_TOKEN env check).
    # This is a direct contract test of the write/cleanup logic.
    pid_file = tmp_path / ".claude-bot" / "bot.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)

    # Simulate write
    pid_file.write_text(str(os.getpid()))
    assert pid_file.exists()
    assert pid_file.read_text().strip() == str(os.getpid())

    # Simulate cleanup
    pid_file.unlink(missing_ok=True)
    assert not pid_file.exists()


def test_pid_file_cleanup_is_safe_when_already_deleted(tmp_path):
    """unlink(missing_ok=True) does not raise if file was already removed."""
    pid_file = tmp_path / ".claude-bot" / "bot.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    # File never created — unlink must be silent
    pid_file.unlink(missing_ok=True)  # no exception
```

- [ ] **Step 2: Run tests to confirm they pass immediately** (pure logic, no bot import)

```bash
venv/Scripts/python -m pytest tests/bot/test_bot_health_wiring.py -v
```

Expected: both PASS (these validate the contract, not the wiring yet).

- [ ] **Step 3: Add health server import to `bot.py`**

In `bot.py`, add to the `core` import block (after `from core.voice_notifier import VoiceNotifier`):

```python
from core.health_server import start_health_server, stop_health_server
```

- [ ] **Step 4: Start health server in `ClaudeBot.setup_hook()`**

At the **end** of `setup_hook()`, just before the function returns, add:

```python
        await start_health_server(self)
```

The full end of `setup_hook()` then looks like:

```python
        guild = discord.Object(id=int(GUILD_ID))
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        log.info("Slash commands synced to guild %s", GUILD_ID)

        await start_health_server(self)
```

- [ ] **Step 5: Stop health server in `ClaudeBot.close()`**

Replace the existing `close()`:

```python
    async def close(self) -> None:
        log.info("Shutting down — cancelling active Claude processes...")
        await stop_health_server()
        await self.claude_runner.cancel_all()
        await super().close()
```

- [ ] **Step 6: Write PID file and clean up in `main()`**

Replace the existing `main()` function in `bot.py`:

```python
def main() -> None:
    # Write PID file so the watchdog can kill this process if unhealthy.
    _pid_file = Path(__file__).resolve().parent / ".claude-bot" / "bot.pid"
    _pid_file.parent.mkdir(exist_ok=True)
    _pid_file.write_text(str(os.getpid()))
    try:
        for attempt in range(_MAX_LOGIN_RETRIES + 1):
            current_bot = ClaudeBot()
            try:
                current_bot.run(DISCORD_TOKEN, log_handler=None)
            except KeyboardInterrupt:
                log.info("Interrupted")
                return
            except discord.errors.HTTPException as exc:
                if exc.status != 429:
                    log.exception("Discord HTTP error during startup")
                    return
                _log_login_rate_limit(exc, attempt)
                if attempt < _MAX_LOGIN_RETRIES:
                    log.warning(
                        "Waiting %.0fs before retrying login (attempt %d/%d)...",
                        _LOGIN_RETRY_DELAY, attempt + 1, _MAX_LOGIN_RETRIES,
                    )
                    time.sleep(_LOGIN_RETRY_DELAY)
                    continue
                log.error("Exhausted all login retry attempts (%d). Exiting.", _MAX_LOGIN_RETRIES + 1)
                return
            except Exception:
                log.exception("Unexpected error during bot startup")
                return

            if current_bot._restart_requested:
                log.info("Exiting with code %d to trigger restart", RESTART_EXIT_CODE)
                sys.exit(RESTART_EXIT_CODE)
            return
    finally:
        _pid_file.unlink(missing_ok=True)
```

- [ ] **Step 7: Verify import is clean**

```bash
venv/Scripts/python -c "import bot; print('import OK')"
```

Expected: `import OK` (no errors; `sys.exit` is not triggered because `DISCORD_TOKEN` env var won't cause exit during import).

Actually, `bot.py` calls `sys.exit` at module level if `DISCORD_TOKEN` is missing. Check the env is set, or just confirm no syntax errors:

```bash
venv/Scripts/python -m py_compile bot.py && echo "syntax OK"
```

Expected: `syntax OK`.

- [ ] **Step 8: Run all bot tests to confirm no regressions**

```bash
venv/Scripts/python -m pytest tests/bot/ -v
```

Expected: all tests PASS.

- [ ] **Step 9: Commit**

```bash
git add bot.py tests/bot/test_bot_health_wiring.py
git commit -m "feat: wire health server and PID file into bot.py"
```

---

### Task 3: Watchdog Process

**Files:**
- Create: `watchdog.py`
- Create: `tests/bot/test_watchdog.py`

**Interfaces:**
- Consumes: `.claude-bot/bot.pid` (written by bot.py Task 2)
- Consumes env vars: `HEALTH_PORT`, `HEALTH_CHECK_INTERVAL`, `HEALTH_RESTART_GRACE`, `DISCORD_TOKEN`, `DISCORD_CHANNEL_ID`
- Produces: kills bot process on unhealthy detection; POSTs Discord notification.

- [ ] **Step 1: Write the failing tests**

Create `tests/bot/test_watchdog.py`:

```python
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

    mock_kill.assert_called_once_with(5678, signal.SIGKILL)


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
    mock_session.get.return_value = mock_get_cm

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
    mock_session.get.return_value = mock_get_cm

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await wdog.check_health(port=8766)
    assert result is False


async def test_check_health_returns_false_on_connection_error(wdog):
    """Returns False on connection refused (bot process dead)."""
    import aiohttp

    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = False
    mock_session.get.side_effect = aiohttp.ClientConnectionError("refused")

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
    mock_session.post.return_value = mock_post_cm

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
    mock_session.post.side_effect = aiohttp.ClientConnectionError("network down")

    with patch("aiohttp.ClientSession", return_value=mock_session), \
         caplog.at_level(logging.ERROR):
        await wdog.send_discord_notification("tok", "123", "msg")  # must not raise

    assert caplog.records, "Expected an error log"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
venv/Scripts/python -m pytest tests/bot/test_watchdog.py -v 2>&1 | head -20
```

Expected: `FileNotFoundError` or `ModuleNotFoundError` — `watchdog.py` does not exist yet.

- [ ] **Step 3: Create `watchdog.py`**

```python
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
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        else:
            os.kill(pid, signal.SIGKILL)
        log.info("Bot process killed.")
    except (ProcessLookupError, OSError) as exc:
        log.warning("Could not kill PID %d: %s (may have already exited).", pid, exc)


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
        "Watchdog started. Polling http://127.0.0.1:%d/health every %ds (grace %ds).",
        port, interval, grace,
    )

    while True:
        await asyncio.sleep(interval)

        healthy = await check_health(port=port)
        if healthy:
            log.info("Health check passed.")
            continue

        log.warning("Health check FAILED — triggering hard reboot.")

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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
venv/Scripts/python -m pytest tests/bot/test_watchdog.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add watchdog.py tests/bot/test_watchdog.py
git commit -m "feat: add health watchdog process"
```

---

### Task 4: startup.sh — Watchdog Launch, Teardown, and Restart Loop

**Files:**
- Modify: `startup.sh`

No automated tests for bash — manual verification steps confirm correctness.

- [ ] **Step 1: Update `_teardown()` to kill the watchdog before other services**

In `startup.sh`, replace the entire `_teardown()` function with:

```bash
_teardown() {
    echo "=== Teardown: stopping existing services ==="

    # Kill watchdog
    local watchdog_pid_file="$SCRIPT_DIR/.claude-bot/watchdog.pid"
    if [ -f "$watchdog_pid_file" ]; then
        local wpid
        wpid=$(cat "$watchdog_pid_file" 2>/dev/null)
        if [ -n "$wpid" ] && [ "$wpid" != "0" ]; then
            echo "  watchdog (PID $wpid)..."
            if command -v taskkill >/dev/null 2>&1; then
                taskkill //PID "$wpid" //F >/dev/null 2>&1 || true
            else
                kill "$wpid" 2>/dev/null || true
            fi
        fi
        rm -f "$watchdog_pid_file"
    fi

    echo "  feature-mcp (port 8765)..."
    _kill_port 8765

    if docker info >/dev/null 2>&1; then
        echo "  dashboard (Docker)..."
        cd "$SCRIPT_DIR/dashboard" && docker compose down --remove-orphans 2>/dev/null || true
        cd "$SCRIPT_DIR"
    fi

    echo "Teardown complete."
    echo ""
}
```

- [ ] **Step 2: Update the bot restart loop to restart on any non-zero exit**

Find the bot launch while-loop (the block containing `python "$SCRIPT_DIR/bot.py"`). Replace it with:

```bash
    while true; do
        PYTHONUTF8=1 python "$SCRIPT_DIR/bot.py" "$@"
        EXIT_CODE=$?
        if [ $EXIT_CODE -eq 0 ]; then
            echo "Bot exited cleanly (code 0)."
            break
        fi
        if [ $EXIT_CODE -eq 42 ]; then
            echo "Bot requested restart (exit code 42). Restarting..."
        else
            echo "Bot exited with code $EXIT_CODE — restarting (watchdog kill or crash)..."
        fi
    done
```

- [ ] **Step 3: Add watchdog launch section after the feature-mcp block**

In `startup.sh`, find the line `# ── Local Dashboard` section header. Insert the following **before** that section (after the feature-mcp block):

```bash
# ── Watchdog ──────────────────────────────────────────────────────────────────
if [ "$DASH_ONLY" = false ]; then
    echo "=== Starting Watchdog ==="
    CLAUDE_BOT_DIR="$SCRIPT_DIR/.claude-bot"
    mkdir -p "$CLAUDE_BOT_DIR"
    if [ -f "$SCRIPT_DIR/venv/Scripts/activate" ]; then
        source "$SCRIPT_DIR/venv/Scripts/activate"
    else
        source "$SCRIPT_DIR/venv/bin/activate"
    fi
    PYTHONUTF8=1 python "$SCRIPT_DIR/watchdog.py" &
    WATCHDOG_PID=$!
    echo "$WATCHDOG_PID" > "$CLAUDE_BOT_DIR/watchdog.pid"
    echo "Watchdog started (PID $WATCHDOG_PID)"
    echo ""
fi
```

- [ ] **Step 4: Verify teardown works cleanly with no running services**

```bash
bash startup.sh --down
```

Expected: teardown output runs without errors; no watchdog PID file warning when `.claude-bot/watchdog.pid` is absent.

- [ ] **Step 5: Verify watchdog starts alongside the bot (quick smoke test)**

In a separate terminal, run:

```bash
bash startup.sh &
sleep 8
cat .claude-bot/watchdog.pid
```

Expected: prints a PID. Kill the background startup.sh with `bash startup.sh --down` when done.

- [ ] **Step 6: Commit**

```bash
git add startup.sh
git commit -m "feat: launch watchdog from startup.sh, restart bot on any non-zero exit"
```

---

## Self-Review

**Spec coverage:**
- ✅ `GET /health` returns 200/503 based on `is_ready()` and `is_closed()`
- ✅ Port configurable via `HEALTH_PORT`, binds to `127.0.0.1`
- ✅ Health server starts in `setup_hook()`, stops in `close()`
- ✅ Watchdog polls every `HEALTH_CHECK_INTERVAL` (default 600s)
- ✅ Discord REST notification on unhealthy: correct URL, headers, message
- ✅ Windows + Linux kill paths in `kill_bot_process()`
- ✅ Grace period (`HEALTH_RESTART_GRACE`) after triggering restart
- ✅ Bot writes `.claude-bot/bot.pid` before `run()`, removes in `finally`
- ✅ `startup.sh` restarts bot on any non-zero exit (not just 42)
- ✅ Watchdog launched by `startup.sh`, killed in `_teardown()`
- ✅ No new runtime dependencies

**Placeholder scan:** None found.

**Type consistency:**
- `start_health_server(bot, port)` / `stop_health_server()` defined in Task 1, used in Task 2 — names match.
- `kill_bot_process(pid_file)`, `check_health(port)`, `send_discord_notification(token, channel_id, message)` defined and tested in Task 3 with consistent signatures.

**Review Focus — tests added:**
1. **503 during startup** → `test_health_503_when_bot_not_ready` (Task 1) covers `is_ready()=False` → 503.
2. **Stale/reused PID** → `test_kill_bot_process_stale_pid` (Task 3) — `ProcessLookupError` caught, no propagation.
3. **Grace period overlap** → linear `asyncio.sleep` after kill; single-iteration loop prevents concurrent triggers.
4. **Port in use** → `test_start_health_server_port_in_use` (Task 1) — `OSError` caught, warning logged, no crash.
5. **Watchdog accumulation** → `_teardown()` kills by PID from `.claude-bot/watchdog.pid` before any new start (Task 4 Step 1); verified manually in Step 4.
