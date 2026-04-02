"""Tests for core.state split feature storage."""
import json
from pathlib import Path

import pytest

from core.state import (
    feature_name_to_filename,
    load_feature_index, save_feature_index,
    load_feature_file, save_feature_file, delete_feature_file,
    list_feature_names,
    _migrate_monolithic_to_split,
)


class TestFeatureNameToFilename:
    def test_spaces_and_ampersand(self):
        assert feature_name_to_filename("Bugs & Fixes") == "bugs_and_fixes"

    def test_hyphens(self):
        assert feature_name_to_filename("feature-closure") == "feature_closure"

    def test_mixed(self):
        assert feature_name_to_filename("Star-trek-personas") == "star_trek_personas"

    def test_already_snake(self):
        assert feature_name_to_filename("my_feature") == "my_feature"

    def test_empty_fallback(self):
        assert feature_name_to_filename("") == "unnamed"

    def test_special_chars_stripped(self):
        assert feature_name_to_filename("feat!@#$%name") == "featname"


class TestSplitStorage:
    def test_save_and_load_index(self, tmp_path):
        index = {"current_feature": "foo", "sessions": {"abc": {"feature": "foo"}}}
        save_feature_index(tmp_path, index)
        loaded = load_feature_index(tmp_path)
        assert loaded["current_feature"] == "foo"
        assert "abc" in loaded["sessions"]

    def test_empty_index(self, tmp_path):
        index = load_feature_index(tmp_path)
        assert index == {"current_feature": None, "sessions": {}}

    def test_save_and_load_feature_file(self, tmp_path):
        data = {"name": "test", "status": "active", "total_input_tokens": 100}
        save_feature_file(tmp_path, "test", data)
        loaded = load_feature_file(tmp_path, "test")
        assert loaded["status"] == "active"
        assert loaded["total_input_tokens"] == 100

    def test_load_nonexistent_feature(self, tmp_path):
        assert load_feature_file(tmp_path, "nope") is None

    def test_delete_feature_file(self, tmp_path):
        save_feature_file(tmp_path, "deleteme", {"name": "deleteme"})
        assert delete_feature_file(tmp_path, "deleteme") is True
        assert load_feature_file(tmp_path, "deleteme") is None
        assert delete_feature_file(tmp_path, "deleteme") is False

    def test_list_feature_names(self, tmp_path):
        save_feature_file(tmp_path, "alpha", {"name": "alpha"})
        save_feature_file(tmp_path, "beta", {"name": "beta"})
        names = list_feature_names(tmp_path)
        assert sorted(names) == ["alpha", "beta"]

    def test_list_empty(self, tmp_path):
        assert list_feature_names(tmp_path) == []


class TestMigration:
    def test_monolithic_to_split(self, tmp_path):
        # Write old-style monolithic features.json
        old = {
            "current_feature": "foo",
            "sessions": {"s1": {"feature": "foo"}},
            "features": {
                "foo": {"status": "active", "total_input_tokens": 500},
                "bar": {"status": "completed", "total_cost_usd": 1.5},
            }
        }
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "features.json").write_text(json.dumps(old))

        # load_feature_index triggers migration
        index = load_feature_index(tmp_path)
        assert index["current_feature"] == "foo"
        assert "s1" in index["sessions"]
        assert "features" not in index  # monolithic key is gone

        # Per-feature files created
        foo = load_feature_file(tmp_path, "foo")
        assert foo["status"] == "active"
        assert foo["total_input_tokens"] == 500

        bar = load_feature_file(tmp_path, "bar")
        assert bar["status"] == "completed"
        assert bar["total_cost_usd"] == 1.5

    def test_already_split_format_untouched(self, tmp_path):
        index = {"current_feature": "x", "sessions": {}}
        save_feature_index(tmp_path, index)
        loaded = load_feature_index(tmp_path)
        assert loaded == index


class TestAccumulateIsolation:
    def test_accumulate_does_not_modify_index(self, tmp_path):
        """accumulate_tokens should only touch the per-feature file, not the index."""
        from core.feature_manager import FeatureManager
        import os

        fm = FeatureManager()
        fm.start_feature(tmp_path, "test-feat")

        index_path = tmp_path / ".claude" / "features.json"
        mtime_before = os.path.getmtime(index_path)

        fm.accumulate_tokens(tmp_path, 1000, 50, 0.01, "test-feat")

        mtime_after = os.path.getmtime(index_path)
        assert mtime_before == mtime_after
