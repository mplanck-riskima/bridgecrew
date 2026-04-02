"""Tests for /api/costs endpoints."""


def test_ingest_cost(client, auth_headers):
    proj = client.post("/api/projects", json={"name": "proj"}).json()

    resp = client.post("/api/costs", json={
        "project_id": proj["project_id"],
        "session_id": "sess-1",
        "model": "claude-sonnet-4-6",
        "cost_usd": 0.05,
        "input_tokens": 1000,
        "output_tokens": 50,
    }, headers=auth_headers)
    assert resp.status_code == 201


def test_ingest_cost_requires_auth(client):
    resp = client.post("/api/costs", json={
        "project_id": "x",
        "session_id": "s",
        "model": "m",
        "cost_usd": 0.01,
    })
    assert resp.status_code == 403


def test_cost_breakdown(client, auth_headers):
    proj = client.post("/api/projects", json={"name": "proj"}).json()
    client.post("/api/costs", json={
        "project_id": proj["project_id"],
        "session_id": "s1",
        "model": "claude-sonnet-4-6",
        "cost_usd": 0.05,
    }, headers=auth_headers)

    resp = client.get("/api/costs/breakdown")
    assert resp.status_code == 200


def test_cost_timeline(client):
    resp = client.get("/api/costs/timeline")
    assert resp.status_code == 200
