"""In-memory fake implementations for bot tests."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from models.feature import Feature


class FakeFeatureManager:
    def __init__(self):
        self._features: dict[str, dict[str, Feature]] = {}  # project_dir_str -> {name -> Feature}
        self._current: dict[str, str | None] = {}  # project_dir_str -> current feature name

    def _key(self, project_dir: Path) -> str:
        return str(project_dir)

    def start_feature(self, project_dir: Path, name: str, subdir: str | None = None) -> Feature:
        k = self._key(project_dir)
        self._features.setdefault(k, {})
        session_id = str(uuid.uuid4())
        feat = Feature(name=name, session_id=session_id, subdir=subdir)
        self._features[k][name] = feat
        self._current[k] = name
        return feat

    def resume_feature(self, project_dir: Path, name: str) -> Feature | None:
        k = self._key(project_dir)
        feat = self._features.get(k, {}).get(name)
        if not feat:
            return None
        feat.session_id = str(uuid.uuid4())
        feat.status = "active"
        self._current[k] = name
        return feat

    def complete_feature(self, project_dir: Path, name: str | None = None, session_id: str | None = None) -> Feature | None:
        k = self._key(project_dir)
        if not name:
            name = self._current.get(k)
        if not name:
            return None
        feat = self._features.get(k, {}).get(name)
        if not feat:
            return None
        feat.status = "completed"
        feat.completed_at = datetime.now(timezone.utc).isoformat()
        if self._current.get(k) == name:
            self._current[k] = None
        return feat

    def get_current_feature(self, project_dir: Path, session_id: str | None = None) -> Feature | None:
        k = self._key(project_dir)
        name = self._current.get(k)
        if not name:
            return None
        feat = self._features.get(k, {}).get(name)
        if feat and feat.status == "completed":
            return None
        return feat

    def list_features(self, project_dir: Path) -> list[Feature]:
        k = self._key(project_dir)
        return list(self._features.get(k, {}).values())

    def accumulate_tokens(self, project_dir: Path, input_tokens: int, output_tokens: int, cost_usd: float, feature_name: str | None = None) -> dict:
        k = self._key(project_dir)
        feat = self._features.get(k, {}).get(feature_name) if feature_name else None
        if feat:
            feat.total_input_tokens += input_tokens
            feat.total_output_tokens += output_tokens
            feat.total_cost_usd += cost_usd
            feat.prompt_count += 1
            return {"total_input_tokens": feat.total_input_tokens, "total_output_tokens": feat.total_output_tokens, "total_cost_usd": feat.total_cost_usd, "prompt_count": feat.prompt_count}
        return {"total_input_tokens": input_tokens, "total_output_tokens": output_tokens, "total_cost_usd": cost_usd, "prompt_count": 1}

    def auto_complete_active_features(self, project_dir: Path, exclude_name: str | None = None) -> list[Feature]:
        k = self._key(project_dir)
        completed = []
        for name, feat in self._features.get(k, {}).items():
            if name == exclude_name or feat.status != "active":
                continue
            feat.status = "completed"
            feat.completed_at = datetime.now(timezone.utc).isoformat()
            completed.append(feat)
        return completed

    def discard_feature(self, project_dir: Path, name: str) -> Feature | None:
        k = self._key(project_dir)
        feat = self._features.get(k, {}).pop(name, None)
        if self._current.get(k) == name:
            self._current[k] = None
        return feat

    def register_cli_session(self, project_dir: Path, cli_session_id: str, feature_name: str) -> Feature | None:
        k = self._key(project_dir)
        feat = self._features.get(k, {}).get(feature_name)
        if feat:
            feat.session_id = cli_session_id
        return feat

    def add_history(self, project_dir: Path, user: str, prompt_summary: str, feature_name: str | None) -> None:
        pass


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
