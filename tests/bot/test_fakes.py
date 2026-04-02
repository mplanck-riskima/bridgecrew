"""Tests that the fake managers behave correctly."""
from pathlib import Path

import pytest

from tests.bot.fakes.managers import FakeFeatureManager


@pytest.fixture
def fm():
    return FakeFeatureManager()


def test_start_and_get(fm):
    d = Path("/tmp/test")
    feat = fm.start_feature(d, "test-feat")
    assert feat.name == "test-feat"
    assert feat.status == "active"
    found = fm.get_current_feature(d)
    assert found is not None
    assert found.name == "test-feat"


def test_complete_clears_current(fm):
    d = Path("/tmp/test")
    fm.start_feature(d, "feat")
    fm.complete_feature(d, "feat")
    assert fm.get_current_feature(d) is None


def test_auto_complete(fm):
    d = Path("/tmp/test")
    fm.start_feature(d, "a")
    fm.start_feature(d, "b")
    completed = fm.auto_complete_active_features(d, exclude_name="b")
    assert len(completed) == 1
    assert completed[0].name == "a"


def test_discard(fm):
    d = Path("/tmp/test")
    fm.start_feature(d, "feat")
    fm.discard_feature(d, "feat")
    assert fm.list_features(d) == []


def test_accumulate(fm):
    d = Path("/tmp/test")
    fm.start_feature(d, "feat")
    totals = fm.accumulate_tokens(d, 100, 10, 0.01, "feat")
    assert totals["total_input_tokens"] == 100
    assert totals["prompt_count"] == 1
