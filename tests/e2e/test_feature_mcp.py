# tests/e2e/test_feature_mcp.py
"""
Real-server smoke tests for feature-mcp.

Requires the feature-mcp server running on localhost:8765.
Start it with: M:/feature-mcp/start.bat

Skipped automatically if the server is not reachable.
"""
import pytest
import httpx
from pathlib import Path
from urllib.parse import quote

SERVER_URL = "http://localhost:8765"


def _enc(path: Path) -> str:
    return quote(str(path), safe="")


def _server_available() -> bool:
    try:
        httpx.get(f"{SERVER_URL}/docs", timeout=2.0)
        return True
    except Exception:
        return False


skip_no_server = pytest.mark.skipif(
    not _server_available(),
    reason="feature-mcp server not running on localhost:8765 — skipping smoke tests",
)


@pytest.fixture
def live_project(tmp_path):
    """Register a fresh temp project with the live server and yield (path, client)."""
    if not _server_available():
        pytest.skip("feature-mcp server not running on localhost:8765 — skipping smoke tests")

    (tmp_path / ".claude" / "features").mkdir(parents=True)
    client = httpx.Client(base_url=SERVER_URL, timeout=10.0)

    r = client.post("/api/projects", json={"project_dir": str(tmp_path)})
    assert r.status_code == 200, f"Failed to register temp project: {r.text}"

    yield tmp_path, client

    # Teardown: discard any leftover active feature (best-effort)
    try:
        client.post(
            f"/api/projects/{_enc(tmp_path)}/sessions/smoke-sess-1/discard"
        )
    except Exception:
        pass
    client.close()


@skip_no_server
def test_live_start_registers_feature(live_project):
    tmp_path, client = live_project
    enc = _enc(tmp_path)

    r = client.post(
        f"/api/projects/{enc}/features/smoke-test/start",
        json={"session_id": "smoke-sess-1"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "started"

    r2 = client.get(f"/api/projects/{enc}/features")
    assert r2.status_code == 200
    features = r2.json()
    assert any(f["name"] == "smoke-test" and f["status"] == "active" for f in features), \
        f"Expected active 'smoke-test' in {features}"


@skip_no_server
def test_live_lifecycle_complete(live_project):
    """Full lifecycle: start → milestone → complete → verify JSON state and markdown."""
    tmp_path, client = live_project
    enc = _enc(tmp_path)
    session_id = "smoke-sess-1"

    # Start
    r = client.post(
        f"/api/projects/{enc}/features/smoke-lifecycle/start",
        json={"session_id": session_id},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "started"

    # Milestone
    r = client.post(
        f"/api/projects/{enc}/sessions/{session_id}/milestone",
        json={"text": "smoke milestone reached"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "added"

    # Complete
    r = client.post(
        f"/api/projects/{enc}/sessions/{session_id}/complete",
        json={"summary": "Smoke test complete."},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    assert r.json()["feature_name"] == "smoke-lifecycle"

    # Verify features list
    r = client.get(f"/api/projects/{enc}/features")
    assert r.status_code == 200
    features = r.json()
    match = next((f for f in features if f["name"] == "smoke-lifecycle"), None)
    assert match is not None, f"Feature not found in {features}"
    assert match["status"] == "completed"

    # Verify markdown file was written to the temp dir
    md_path = tmp_path / "features" / "smoke-lifecycle.md"
    assert md_path.exists(), f"Markdown not written to {md_path}"
    content = md_path.read_text()
    assert "Smoke test complete." in content
    assert "smoke milestone reached" in content


@skip_no_server
def test_server_rejects_unknown_project(live_project):
    _, client = live_project
    r = client.post(
        f"/api/projects/{_enc(Path('/absolutely/nonexistent/path'))}/features/x/start",
        json={"session_id": "s"},
    )
    assert r.status_code == 404
