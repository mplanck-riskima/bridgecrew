"""Scans ~/.claude/projects/**/*.jsonl to compute daily and weekly token usage."""
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Anthropic pricing per million tokens (as of 2025)
_PRICING: dict[str, dict[str, float]] = {
    "opus": {
        "input": 15.0,
        "cache_read": 1.50,
        "cache_write": 18.75,
        "output": 75.0,
    },
    "sonnet": {
        "input": 3.0,
        "cache_read": 0.30,
        "cache_write": 3.75,
        "output": 15.0,
    },
    "haiku": {
        "input": 0.80,
        "cache_read": 0.08,
        "cache_write": 1.0,
        "output": 4.0,
    },
}


def _model_tier(model_name: str) -> str:
    if "opus" in model_name:
        return "opus"
    if "haiku" in model_name:
        return "haiku"
    return "sonnet"


def _estimate_cost(model_name: str, input_tokens: int, cache_read: int, cache_write: int, output_tokens: int) -> float:
    tier = _model_tier(model_name)
    p = _PRICING[tier]
    m = 1_000_000
    return (
        input_tokens * p["input"] / m
        + cache_read * p["cache_read"] / m
        + cache_write * p["cache_write"] / m
        + output_tokens * p["output"] / m
    )


@dataclass
class UsagePeriod:
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    request_count: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens + self.output_tokens


@dataclass
class UsageSummary:
    five_hour: UsagePeriod = field(default_factory=UsagePeriod)
    today: UsagePeriod = field(default_factory=UsagePeriod)
    this_week: UsagePeriod = field(default_factory=UsagePeriod)
    daily_resets_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    weekly_resets_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _next_midnight_utc(now: datetime) -> datetime:
    """Returns the next midnight UTC."""
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def _next_monday_utc(now: datetime) -> datetime:
    """Returns next Monday midnight UTC."""
    days_until_monday = (7 - now.weekday()) % 7 or 7
    return (now + timedelta(days=days_until_monday)).replace(hour=0, minute=0, second=0, microsecond=0)


def get_usage_summary(claude_dir: Path | None = None) -> UsageSummary:
    """Scan all Claude session JSONL files and return a UsageSummary.

    Deduplicates by requestId, keeping only the final assistant turn per request
    (entries with stop_reason set, i.e. not None) to avoid double-counting
    streaming intermediate payloads.
    """
    if claude_dir is None:
        claude_dir = Path.home() / ".claude" / "projects"

    now = datetime.now(timezone.utc)
    five_hour_cutoff = now - timedelta(hours=5)
    today_cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Weekly: start of current week (Monday)
    week_cutoff = today_cutoff - timedelta(days=today_cutoff.weekday())

    summary = UsageSummary(
        daily_resets_at=_next_midnight_utc(now),
        weekly_resets_at=_next_monday_utc(now),
    )

    if not claude_dir.exists():
        return summary

    # requestId -> best (final) record: {ts, model, input, cache_read, cache_write, output}
    seen: dict[str, dict] = {}

    for jsonl_file in claude_dir.rglob("*.jsonl"):
        try:
            with open(jsonl_file, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if entry.get("type") != "assistant":
                        continue

                    request_id = entry.get("requestId")
                    if not request_id:
                        continue

                    msg = entry.get("message", {})
                    usage = msg.get("usage", {})
                    if not usage:
                        continue

                    ts_str = entry.get("timestamp")
                    if not ts_str:
                        continue
                    try:
                        ts = datetime.fromisoformat(ts_str.rstrip("Z")).replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue

                    stop_reason = msg.get("stop_reason")
                    model = msg.get("model", "")

                    record = {
                        "ts": ts,
                        "model": model,
                        "input": usage.get("input_tokens", 0),
                        "cache_read": usage.get("cache_read_input_tokens", 0),
                        "cache_write": usage.get("cache_creation_input_tokens", 0),
                        "output": usage.get("output_tokens", 0),
                        "is_final": stop_reason is not None,
                    }

                    existing = seen.get(request_id)
                    # Prefer final entries; among finals or non-finals, prefer later timestamps
                    if existing is None:
                        seen[request_id] = record
                    elif record["is_final"] and not existing["is_final"]:
                        seen[request_id] = record
                    elif record["is_final"] == existing["is_final"] and record["ts"] > existing["ts"]:
                        seen[request_id] = record

        except OSError:
            continue

    # Aggregate into periods
    for record in seen.values():
        ts = record["ts"]
        if ts < week_cutoff:
            continue

        cost = _estimate_cost(record["model"], record["input"], record["cache_read"], record["cache_write"], record["output"])

        periods = [summary.this_week]
        if ts >= today_cutoff:
            periods.append(summary.today)
        if ts >= five_hour_cutoff:
            periods.append(summary.five_hour)

        for period in periods:
            period.input_tokens += record["input"]
            period.cache_read_tokens += record["cache_read"]
            period.cache_write_tokens += record["cache_write"]
            period.output_tokens += record["output"]
            period.cost_usd += cost
            period.request_count += 1

    return summary


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def fmt_time_until(dt: datetime) -> str:
    """Returns a human-readable 'in X.Xh' string until dt."""
    now = datetime.now(timezone.utc)
    delta = dt - now
    if delta.total_seconds() <= 0:
        return "now"
    hours = delta.total_seconds() / 3600
    return f"in {hours:.1f}h"
