"""Tests for /api/features endpoints."""


def test_list_features_empty(client):
    resp = client.get("/api/features")
    assert resp.status_code == 200
    data = resp.json()
    # Paginated response
    assert data["items"] == []
    assert data["total"] == 0


def test_create_feature(client, auth_headers):
    # Create a project first
    proj = client.post("/api/projects", json={"name": "proj"}).json()

    resp = client.post("/api/features", json={
        "project_id": proj["project_id"],
        "name": "test-feature",
        "session_id": "abc-123",
    }, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test-feature"
    assert "feature_id" in data


def test_create_feature_requires_auth(client):
    resp = client.post("/api/features", json={
        "project_id": "x",
        "name": "feat",
        "session_id": "abc",
    })
    assert resp.status_code == 403


def test_update_feature(client, auth_headers):
    proj = client.post("/api/projects", json={"name": "proj"}).json()
    feat = client.post("/api/features", json={
        "project_id": proj["project_id"],
        "name": "feat",
        "session_id": "abc",
    }, headers=auth_headers).json()

    resp = client.patch(f"/api/features/{feat['feature_id']}", json={
        "status": "completed",
    }, headers=auth_headers)
    assert resp.status_code == 200
