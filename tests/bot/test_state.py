"""Tests for core.state project state storage."""
import json
from pathlib import Path

import pytest

from core.state import load_project_state, save_project_state, load_config, save_config


class TestProjectState:
    def test_load_missing_returns_default(self, tmp_path):
        state = load_project_state(tmp_path)
        assert state == {"history": []}

    def test_save_and_load(self, tmp_path):
        state = {"history": [], "default_session_id": "abc123"}
        save_project_state(tmp_path, state)
        loaded = load_project_state(tmp_path)
        assert loaded["default_session_id"] == "abc123"

    def test_save_creates_directory(self, tmp_path):
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        state = {"history": [{"user": "u1", "prompt_summary": "hello"}]}
        save_project_state(project_dir, state)
        loaded = load_project_state(project_dir)
        assert loaded["history"][0]["user"] == "u1"
