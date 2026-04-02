"""Tests for /api/prompts endpoints."""


def test_list_prompts_empty(client):
    resp = client.get("/api/prompts")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_and_list_prompt(client):
    resp = client.post("/api/prompts", json={
        "name": "Kirk",
        "description": "Bold captain",
        "content": "You are Captain Kirk...",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data  # API returns "id" not "prompt_id"

    resp = client.get("/api/prompts")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_update_prompt(client):
    created = client.post("/api/prompts", json={
        "name": "Kirk",
        "content": "original",
    }).json()
    pid = created["id"]

    resp = client.put(f"/api/prompts/{pid}", json={"content": "updated"})
    assert resp.status_code == 200


def test_delete_prompt(client):
    created = client.post("/api/prompts", json={
        "name": "Deleteme",
        "content": "tmp",
    }).json()
    pid = created["id"]

    resp = client.delete(f"/api/prompts/{pid}")
    assert resp.status_code in (200, 204)
