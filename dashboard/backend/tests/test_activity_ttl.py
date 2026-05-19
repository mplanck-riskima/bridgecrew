"""Test that POST /api/activity accepts ttl_days and writes expires_at."""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient


def _make_app():
    from fastapi import FastAPI
    from app.routers.activity import router
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_activity_without_ttl_has_no_expires_at():
    inserted = {}

    def fake_insert(doc):
        inserted.update(doc)
        m = MagicMock()
        m.inserted_id = "abc123"
        return m

    with patch("app.routers.activity.activity_col") as mock_col:
        mock_col.return_value.insert_one.side_effect = fake_insert
        client = TestClient(_make_app())
        resp = client.post("/api/activity", json={
            "project_id": "proj1", "role": "user", "author": "Alice", "content": "hi"
        })
    assert resp.status_code == 201
    assert "expires_at" not in inserted


def test_activity_with_ttl_sets_expires_at():
    inserted = {}

    def fake_insert(doc):
        inserted.update(doc)
        m = MagicMock()
        m.inserted_id = "abc123"
        return m

    with patch("app.routers.activity.activity_col") as mock_col:
        mock_col.return_value.insert_one.side_effect = fake_insert
        client = TestClient(_make_app())
        resp = client.post("/api/activity", json={
            "project_id": "proj1", "role": "user", "author": "Alice",
            "content": "hi", "ttl_days": 14
        })
    assert resp.status_code == 201
    assert "expires_at" in inserted
    delta = inserted["expires_at"] - inserted["created_at"]
    assert 13 < delta.days < 15
