# Robust Restart — Health Check & Auto-Reboot Design

**Date:** 2026-10-12  
**Feature:** robust-restart  
**Author:** Maxwell Planck

---

## Overview

Add an external health watchdog that monitors the Discord bot every 10 minutes via an HTTP
health endpoint. If the bot is unresponsive or unhealthy, the watchdog kills the bot process
(triggering an automatic restart via the existing `startup.sh` loop) and immediately notifies
the main Discord channel via the REST API.

**Success criteria:**
- A frozen or crashed bot is detected within 10 minutes and automatically restarted.
- The main Discord channel receives a message when a hard reboot is triggered.
- No new Python package dependencies are introduced.
- The watchdog starts and stops cleanly with `startup.sh`.

---

## Components

### 1. Health Endpoint — `core/health_server.py`

A lightweight `aiohttp.web` server (aiohttp is already a transitive dependency via discord.py)
running inside the bot's asyncio event loop.

**Endpoint:** `GET /health`

| Condition | Status | Body |
|-----------|--------|------|
| `bot.is_ready()` and not `bot.is_closed()` | `200 OK` | `{"status": "ok"}` |
| Otherwise | `503 Service Unavailable` | `{"status": "unhealthy"}` |

**Configuration:** Port via `HEALTH_PORT` env var, default `8766`.

**Lifecycle:**
- `start_health_server(bot)` called from `bot.setup_hook()` — creates the aiohttp app and
  starts it as a background asyncio task.
- `stop_health_server()` called from `bot.close()` — gracefully shuts down the site runner.

---

### 2. Watchdog Process — `watchdog.py`

A standalone Python script at the project root, launched by `startup.sh` as a background
process. It inherits all environment variables exported by `startup.sh` from `.env.production`.

**Configuration (env vars):**

| Variable | Default | Purpose |
|----------|---------|---------|
| `HEALTH_PORT` | `8766` | Port to poll |
| `HEALTH_CHECK_INTERVAL` | `600` | Seconds between checks |
| `HEALTH_RESTART_GRACE` | `120` | Seconds to skip checks after triggering a restart |
| `DISCORD_TOKEN` | required | Bot token for REST API notification |
| `DISCORD_CHANNEL_ID` | required | Main channel ID to notify |

**Loop:**
1. Sleep `HEALTH_CHECK_INTERVAL` seconds.
2. `GET http://localhost:{HEALTH_PORT}/health` with a 10-second timeout.
3. If connection error or non-200 response → trigger restart (see below).
4. Otherwise log "healthy" and loop.

**Restart sequence:**
1. POST message to Discord REST API:
   `POST https://discord.com/api/v10/channels/{CHANNEL_ID}/messages`  
   `Authorization: Bot {TOKEN}`  
   Body: `{"content": "⚠️ **Hard reboot triggered** — bridgecrew was unresponsive and has been automatically restarted."}`
2. Read bot PID from `.claude-bot/bot.pid`.
3. Kill the bot process:
   - Windows: `taskkill /F /PID {pid}`
   - Linux/macOS: `os.kill(pid, signal.SIGKILL)`
4. Enter grace period (`HEALTH_RESTART_GRACE` seconds) before resuming checks.

**PID file:** `.claude-bot/bot.pid` — written by `bot.py` at startup, read by watchdog on
restart. If the file is missing or the PID is stale, the watchdog logs a warning and skips
the kill step (the bot may have already crashed; the startup.sh loop will restart it).

**Watchdog PID:** Written to `.claude-bot/watchdog.pid` by `startup.sh` after launching the
watchdog, so teardown can kill it cleanly.

---

### 3. Changes to `bot.py`

**Write PID file on startup:**
In `main()`, before `current_bot.run(DISCORD_TOKEN, ...)`, write `os.getpid()` to
`.claude-bot/bot.pid`. Clean up the file on exit (in a `finally` block).

**Start/stop health server:**
- In `setup_hook()`: call `await start_health_server(self)` from `core.health_server`.
- In `close()`: call `await stop_health_server()` before `super().close()`.

**on_ready — hard reboot notification (optional marker):**
The watchdog sends the Discord notification directly via REST, so no additional marker or
on_ready message is required for the reboot event. The existing `.restarting` marker and
"I'm back online!" message remain unchanged for manual `/restart-bot` flows.

---

### 4. Changes to `startup.sh`

**Restart loop — always restart on non-zero exit:**

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
        echo "Bot exited with code $EXIT_CODE. Restarting..."
    fi
done
```

Previously the loop only continued on exit 42. Now any non-zero exit (including being killed
by the watchdog) causes a restart.

**Launch watchdog after feature-mcp:**

```bash
echo "=== Starting Watchdog ==="
CLAUDE_BOT_DIR="$SCRIPT_DIR/.claude-bot"
mkdir -p "$CLAUDE_BOT_DIR"
python "$SCRIPT_DIR/watchdog.py" &
WATCHDOG_PID=$!
echo "$WATCHDOG_PID" > "$CLAUDE_BOT_DIR/watchdog.pid"
echo "Watchdog started (PID $WATCHDOG_PID)"
```

**Teardown kills watchdog:**
In `_teardown()`, read `.claude-bot/watchdog.pid` and kill the process before tearing down
other services.

---

## Process Topology

```
startup.sh
  ├── feature-mcp/start.sh   (background, port 8765)
  ├── watchdog.py             (background, persistent across bot restarts)
  │     └── polls http://localhost:8766/health every 10 min
  └── while loop
        └── bot.py            (foreground; restarts on any non-zero exit)
              └── aiohttp health server on :8766
```

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Bot process not found (PID stale/missing) | Watchdog logs warning; startup.sh loop may already be restarting |
| Discord REST notification fails | Watchdog logs error and proceeds with kill anyway |
| Health server fails to bind (port in use) | Log warning; bot continues without health endpoint; watchdog will never get 200 and will keep restarting — operator must investigate |
| Watchdog killed before bot | No health monitoring; bot continues running normally |
| Multiple watchdog processes | Teardown kills by PID; only one watchdog launched per startup.sh run |

---

## Files Changed / Created

| File | Change |
|------|--------|
| `core/health_server.py` | **New** — aiohttp health endpoint |
| `watchdog.py` | **New** — health watchdog process |
| `bot.py` | Modified — PID file write, start/stop health server |
| `startup.sh` | Modified — watchdog launch, teardown kill, loop restart policy |

---

## Out of Scope

- Dashboard integration (health status widget) — can be added later
- Alerting on repeated restarts (e.g., 3 reboots in 30 min) — future work
- Health checks for feature-mcp or the dashboard services — future work
