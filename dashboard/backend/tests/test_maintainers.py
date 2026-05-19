"""Tests for maintainers CRUD and prompt construction."""
from unittest.mock import patch, MagicMock
from bson import ObjectId
from fastapi.testclient import TestClient


def _make_app():
    from fastapi import FastAPI
    from app.routers.maintainers import router
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def _fake_maintainer(extra=None):
    doc = {
        "_id": ObjectId("507f1f77bcf86cd799439011"),
        "project_id": "proj1",
        "name": "Daily Log Check",
        "cron_expr": "0 9 * * *",
        "enabled": True,
        "log_sources": "Railway logs at /logs",
        "detection_instructions": "Look for ERROR lines",
        "fix_instructions": "Restart the service",
        "log_ttl_days": 7,
        "last_run": None,
        "last_status": "unknown",
    }
    if extra:
        doc.update(extra)
    return doc


def test_list_maintainers():
    with patch("app.routers.maintainers.project_maintainers_col") as mc:
        mc.return_value.find.return_value = [_fake_maintainer()]
        client = TestClient(_make_app())
        resp = client.get("/api/maintainers?project_id=proj1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Daily Log Check"
    assert "id" in data[0]
    assert "_id" not in data[0]


def test_create_maintainer():
    inserted_doc = {}

    def fake_insert(doc):
        inserted_doc.update(doc)
        m = MagicMock()
        m.inserted_id = ObjectId("507f1f77bcf86cd799439011")
        return m

    with patch("app.routers.maintainers.project_maintainers_col") as mc, \
         patch("app.routers.maintainers.sched") as ms:
        mc.return_value.insert_one.side_effect = fake_insert
        client = TestClient(_make_app())
        resp = client.post("/api/maintainers", json={
            "project_id": "proj1",
            "name": "Daily Log Check",
            "cron_expr": "0 9 * * *",
            "log_sources": "Railway logs",
            "detection_instructions": "Look for ERROR",
            "fix_instructions": "Restart service",
            "log_ttl_days": 7,
        })
    assert resp.status_code == 201
    assert resp.json()["name"] == "Daily Log Check"
    ms.reload_schedules.assert_called_once()


def test_build_prompt():
    from app.routers.maintainers import _build_prompt
    project_name = "my-app"
    maintainer = {
        "log_sources": "Railway logs",
        "detection_instructions": "Look for ERROR lines",
        "fix_instructions": "Restart the failing service",
        "log_ttl_days": 14,
    }
    prompt = _build_prompt(project_name, maintainer)
    assert "my-app" in prompt
    assert "Railway logs" in prompt
    assert "Look for ERROR lines" in prompt
    assert "Restart the failing service" in prompt
    assert "[scheduled-order]" in prompt
    assert "[maintainer-run:14]" in prompt
