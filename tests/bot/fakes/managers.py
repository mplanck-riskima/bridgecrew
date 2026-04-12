"""In-memory fake implementations for bot tests."""
from __future__ import annotations

from pathlib import Path


class FakeProjectManager:
    def __init__(self, projects: dict | None = None, workspace: Path | None = None):
        self._projects = projects or {}  # thread_id -> project
        self.workspace = workspace or Path("/tmp/test-workspace")
        self.channel_id = 123456789

    def get_project_by_thread(self, thread_id: int):
        return self._projects.get(thread_id)

    def get_project_dir(self, project) -> Path:
        return self.workspace / project.name


class FakeClaudeRunner:
    def __init__(self):
        self._busy: set[int] = set()

    def is_busy(self, thread_id: int) -> bool:
        return thread_id in self._busy

    def cancel(self, thread_id: int) -> bool:
        if thread_id in self._busy:
            self._busy.discard(thread_id)
            return True
        return False

    def get_active_info(self, thread_id: int) -> tuple[str, float] | None:
        if thread_id in self._busy:
            return ("test prompt", 5.0)
        return None


class FakeVoiceNotifier:
    def __init__(self):
        self.events: list[tuple] = []

    async def voice_event(self, guild, event_type: str, message: str) -> None:
        self.events.append((event_type, message))
