# robust-restart

**Started:** 2026-10-13  
**Completed:** 2026-11-16  
**Cost:** $0.7215

## Summary

robust-restart adds reliable bot restart and hang recovery. Key additions: an aiohttp /health endpoint (core/health_server.py) with a PID file written by bot.py; a health watchdog (watchdog.py) launched from startup.sh that kills an unresponsive bot and triggers relaunch; and a restart loop in startup.sh that relaunches the bot on any non-zero exit. Final session fixed end-to-end restart: (1) startup.sh used set -e, aborting before capturing exit code 42 — fixed with `python bot.py || EXIT_CODE=$?`; (2) shutdown stall due to aiohttp AppRunner holding connections up to 60s — fixed with shutdown_timeout=1.0 and asyncio.wait_for wrapping stop_health_server/cancel_all; (3) Discord error 10062 (expired interaction) logged as traceback — downgraded to one-line warning; (4) core/mcp_client.restart_server() now treats httpx.ReadError/ReadTimeout as expected mid-response disconnect; (5) removed duplicate "Kill bot" block from startup.sh _teardown. Files changed: bot.py, startup.sh, core/health_server.py, core/mcp_client.py, watchdog.py.
