# orders-improvements

**Started:** 2026-05-20  
**Completed:** 2026-10-03  
**Cost:** $0.7387

## Summary

Hardened the bot's Discord reliability and scheduled-order routing. (1) Rate-limit handling: core/discord_streamer.py `discord_retry` now retries on 429s (honouring X-RateLimit-Reset-After) and `RateLimited`, in addition to 5xx, and a new `_log_rate_limit_info` logs scope/bucket/global/limit details; message-edit failures with 429 log those details instead of generic warnings. (2) bot.py: `main()` now creates a fresh ClaudeBot per attempt and retries login up to 4 times with a 65s delay on 429 (Discord error 40062, whose reported retry_after is unreliable), logging rate-limit headers via `_log_login_rate_limit`; Windows stdout/stderr are reconfigured to UTF-8 so Unicode in logs doesn't crash logging. (3) discord_cogs/claude_prompt.py: scheduled orders may carry a `[scheduled-project:<id>]` marker, which is stripped from the prompt and used to resolve the correct project/dir by matching `bridgecrew_project_id` in project state when no project is otherwise known. Also added scripts/setup-scheduler.ps1 and features/orders-improvements.md. Design decisions: new bot instance per login retry (a failed discord.py client can't be reused), fixed long wait for 40062 rather than trusting headers, and project resolution via stored bridgecrew_project_id rather than channel.
