from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Feature:
    name: str
    session_id: str
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "active"

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "Feature":
        return cls(
            name=name,
            session_id=data["session_id"],
            started_at=data.get("started_at", ""),
            status=data.get("status", "active"),
        )
