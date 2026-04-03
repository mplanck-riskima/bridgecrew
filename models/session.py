from dataclasses import dataclass
from datetime import datetime


@dataclass
class StreamEvent:
    type: str  # "text", "tool_use", "error", "result", "rate_limit", "cancelled"
    content: str = ""
    session_id: str | None = None
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    context_window: int | None = None
    model: str | None = None
    # Rate limit info from rate_limit_event (attached to result event).
    # Maps rateLimitType -> resetsAt (Unix timestamp), e.g.:
    #   {"seven_day_sonnet": 1775246400, "daily_opus": 1775203200}
    rate_limits: dict | None = None


@dataclass
class CliSessionInfo:
    """Metadata about a CLI session discovered on disk."""
    session_id: str
    timestamp: datetime
    first_message: str  # preview of the first user message
    file_path: str  # absolute path to the JSONL file
    feature: str | None = None  # feature name if already linked
