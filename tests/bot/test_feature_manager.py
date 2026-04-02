"""Tests for core.feature_manager using real file system."""
from pathlib import Path

import pytest

from core.feature_manager import FeatureManager
from core.state import load_feature_index, load_feature_file


@pytest.fixture
def fm():
    return FeatureManager()


class TestStartFeature:
    def test_creates_feature_file(self, fm, tmp_path):
        feat = fm.start_feature(tmp_path, "my-feat")
        assert feat.name == "my-feat"
        assert feat.status == "active"
        data = load_feature_file(tmp_path, "my-feat")
        assert data is not None
        assert data["status"] == "active"

    def test_sets_current_feature_in_index(self, fm, tmp_path):
        fm.start_feature(tmp_path, "my-feat")
        index = load_feature_index(tmp_path)
        assert index["current_feature"] == "my-feat"

    def test_registers_session_in_index(self, fm, tmp_path):
        feat = fm.start_feature(tmp_path, "my-feat")
        index = load_feature_index(tmp_path)
        assert feat.session_id in index["sessions"]
        assert index["sessions"][feat.session_id]["feature"] == "my-feat"

    def test_subdir(self, fm, tmp_path):
        feat = fm.start_feature(tmp_path, "sub-feat", subdir="src")
        assert feat.subdir == "src"


class TestResumeFeature:
    def test_resumes_with_new_session(self, fm, tmp_path):
        orig = fm.start_feature(tmp_path, "feat")
        fm.complete_feature(tmp_path, "feat")
        resumed = fm.resume_feature(tmp_path, "feat")
        assert resumed is not None
        assert resumed.session_id != orig.session_id
        assert resumed.status == "active"

    def test_nonexistent_returns_none(self, fm, tmp_path):
        assert fm.resume_feature(tmp_path, "nope") is None


class TestCompleteFeature:
    def test_marks_completed(self, fm, tmp_path):
        fm.start_feature(tmp_path, "feat")
        completed = fm.complete_feature(tmp_path, "feat")
        assert completed.status == "completed"
        assert completed.completed_at is not None

    def test_removes_sessions_from_index(self, fm, tmp_path):
        feat = fm.start_feature(tmp_path, "feat")
        fm.complete_feature(tmp_path, "feat")
        index = load_feature_index(tmp_path)
        assert feat.session_id not in index["sessions"]
        assert index["current_feature"] is None

    def test_by_session_id(self, fm, tmp_path):
        feat = fm.start_feature(tmp_path, "feat")
        completed = fm.complete_feature(tmp_path, session_id=feat.session_id)
        assert completed.name == "feat"

    def test_nonexistent_returns_none(self, fm, tmp_path):
        assert fm.complete_feature(tmp_path, "nope") is None


class TestGetCurrentFeature:
    def test_finds_by_session_id(self, fm, tmp_path):
        feat = fm.start_feature(tmp_path, "feat")
        found = fm.get_current_feature(tmp_path, session_id=feat.session_id)
        assert found is not None
        assert found.name == "feat"

    def test_returns_none_for_completed(self, fm, tmp_path):
        feat = fm.start_feature(tmp_path, "feat")
        fm.complete_feature(tmp_path, "feat")
        found = fm.get_current_feature(tmp_path, session_id=feat.session_id)
        assert found is None

    def test_falls_back_to_current_feature(self, fm, tmp_path):
        fm.start_feature(tmp_path, "feat")
        found = fm.get_current_feature(tmp_path)
        assert found is not None
        assert found.name == "feat"


class TestAutoComplete:
    def test_completes_active_except_excluded(self, fm, tmp_path):
        fm.start_feature(tmp_path, "a")
        fm.start_feature(tmp_path, "b")
        completed = fm.auto_complete_active_features(tmp_path, exclude_name="b")
        assert len(completed) == 1
        assert completed[0].name == "a"
        assert completed[0].status == "completed"

    def test_leaves_excluded_active(self, fm, tmp_path):
        fm.start_feature(tmp_path, "a")
        fm.start_feature(tmp_path, "b")
        fm.auto_complete_active_features(tmp_path, exclude_name="b")
        b = load_feature_file(tmp_path, "b")
        assert b["status"] == "active"


class TestDiscardFeature:
    def test_removes_feature_file(self, fm, tmp_path):
        fm.start_feature(tmp_path, "feat")
        discarded = fm.discard_feature(tmp_path, "feat")
        assert discarded.name == "feat"
        assert load_feature_file(tmp_path, "feat") is None

    def test_clears_index(self, fm, tmp_path):
        feat = fm.start_feature(tmp_path, "feat")
        fm.discard_feature(tmp_path, "feat")
        index = load_feature_index(tmp_path)
        assert feat.session_id not in index["sessions"]
        assert index["current_feature"] is None


class TestRegisterCliSession:
    def test_wires_session_into_feature(self, fm, tmp_path):
        fm.start_feature(tmp_path, "feat")
        result = fm.register_cli_session(tmp_path, "cli-123", "feat")
        assert result is not None
        index = load_feature_index(tmp_path)
        assert "cli-123" in index["sessions"]
        assert index["sessions"]["cli-123"]["source"] == "cli"

    def test_nonexistent_feature_returns_none(self, fm, tmp_path):
        assert fm.register_cli_session(tmp_path, "cli-123", "nope") is None


class TestAccumulateTokens:
    def test_accumulates_to_feature(self, fm, tmp_path):
        fm.start_feature(tmp_path, "feat")
        totals = fm.accumulate_tokens(tmp_path, 1000, 50, 0.01, "feat")
        assert totals["total_input_tokens"] == 1000
        assert totals["prompt_count"] == 1
        totals = fm.accumulate_tokens(tmp_path, 2000, 100, 0.02, "feat")
        assert totals["total_input_tokens"] == 3000
        assert totals["prompt_count"] == 2

    def test_accumulates_to_project_without_feature(self, fm, tmp_path):
        totals = fm.accumulate_tokens(tmp_path, 500, 25, 0.005)
        assert totals["total_input_tokens"] == 500
