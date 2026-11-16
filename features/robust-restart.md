# robust-restart

**Started:** 2026-10-13  
**Completed:** 2026-10-16  
**Cost:** $0.7215

## Summary

robust-restart set out to make the Discord bot restart reliably and recover from hangs. Earlier sessions added an aiohttp /health endpoint (core/health_server.py), a PID file written by bot.py, a health watchdog (watchdog.py) launched from startup.sh that kills an unresponsive bot, and a restart loop in startup.sh that relaunches the bot on any non-zero exit. This final session fixed the reasons /restart-bot still did not work end to end.

Root causes found and fixed:
1. startup.sh runs under `set -e`, so when bot.py exited with code 42 (the restart code) the script aborted before capturing the exit code, and the bot was never relaunched. The launch line is now `python bot.py || EXIT_CODE=$?` with EXIT_CODE initialised to 0, matching the pattern already used in feature-mcp/start.sh.
2. Shutdown could stall: aiohttp's AppRunner waits up to 60s for open keep-alive connections (such as the watchdog's) on cleanup. The runner now uses shutdown_timeout=1.0, and ClaudeBot.close() in bot.py wraps stop_health_server() and claude_runner.cancel_all() in a 10s asyncio.wait_for so one stuck step cannot block exit.
3. The tree.error handler in bot.py now treats Discord error 10062 (Unknown interaction, e.g. an interaction that expired during startup or was acked by another instance) as a one-line warning instead of a full traceback plus a doomed reply attempt.
4. core/mcp_client.restart_server() now also treats httpx.ReadError and ReadTimeout as the expected mid-response disconnect when feature-mcp exits for its own restart, removing a spurious warning.
5. Removed a duplicated "Kill bot" block from _teardown in startup.sh.

Verification: py_compile on changed files, bash -n on startup.sh, and the 12 health-related tests pass. A live restart cycle showed exit 42, relaunch, login, and /health returning 200.

Known gaps and follow-ups: two stray watchdog.py process trees were observed because watchdog.pid tracks only one PID; teardown could kill by process name or the watchdog could use a lock. The ReadError change was made without seeing the actual exception class, since the log message was empty; logging the exception repr would confirm. Console output after login is routed through the bot logger, so it can look hung when it is not.

Files changed: bot.py, startup.sh, core/health_server.py, core/mcp_client.py.
