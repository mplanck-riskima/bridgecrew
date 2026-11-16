# rate-limit-from-statusline

**Started:** 2026-10-19  
**Completed:** 2026-10-19  
**Cost:** $0.0000

## Summary

Read real Claude quota percentages from statusline.sh state file instead of estimating from JSONL token counts + PLAN_*_QUOTA_USD env vars.

Changes:
- statusline.sh: after each CLI response, writes `.rate_limits` JSON to ~/.claude/state/rate_limits.json
- core/usage_tracker.py: added RateLimits dataclass and get_rate_limits() which reads that file
- discord_cogs/status.py: _build_usage_lines() now calls get_rate_limits() for real percentages, removed PLAN_5H_QUOTA_USD/PLAN_7D_QUOTA_USD env var dependency and unused `import os`

The /status command now shows the same authoritative percentages as the CLI status line, sourced directly from Anthropic API response headers via the CLI.
