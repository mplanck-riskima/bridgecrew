"""Protocol interfaces for dependency injection in tests."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class IProjectManager(Protocol):
    def get_project_by_thread(self, thread_id: int) -> object | None: ...
    def get_project_dir(self, project: object) -> Path: ...


@runtime_checkable
class IClaudeRunner(Protocol):
    def is_busy(self, thread_id: int) -> bool: ...
    def cancel(self, thread_id: int) -> bool: ...
    def get_active_info(self, thread_id: int) -> tuple[str, float] | None: ...


@runtime_checkable
class IVoiceNotifier(Protocol):
    async def voice_event(self, guild: object, event_type: str, message: str) -> None: ...
