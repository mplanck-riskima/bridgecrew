"""Tests for /api/projects endpoints."""


def test_list_projects_empty(client):
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_and_get_project(client):
    resp = client.post("/api/projects", json={"name": "test-project", "description": "A test"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test-project"
    project_id = data["project_id"]

    resp = client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "test-project"


def test_update_project(client):
    resp = client.post("/api/projects", json={"name": "original"})
    project_id = resp.json()["project_id"]

    resp = client.put(f"/api/projects/{project_id}", json={"name": "updated"})
    assert resp.status_code == 200

    resp = client.get(f"/api/projects/{project_id}")
    assert resp.json()["name"] == "updated"


def test_delete_project(client):
    resp = client.post("/api/projects", json={"name": "to-delete"})
    project_id = resp.json()["project_id"]

    resp = client.delete(f"/api/projects/{project_id}")
    assert resp.status_code in (200, 204)


def test_get_nonexistent_project(client):
    resp = client.get("/api/projects/nonexistent")
    assert resp.status_code == 404
