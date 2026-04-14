# Feature Lifecycle E2E Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add full-lifecycle E2E tests for feature-mcp covering all four lifecycle paths (happy path, conflict, resume, discard) in-process, plus a real-server smoke test against localhost:8765.

**Architecture:** Three tasks in dependency order. Task 1 adds REST lifecycle endpoints to `rest_api.py` (imported by Task 3's smoke test). Task 2 adds in-process E2E tests using `FakeMCP` + `TestClient`. Task 3 adds real-server smoke tests in the `bridgecrew` repo that call the new REST endpoints.

**Tech Stack:** pytest, FastAPI TestClient, httpx, FakeMCP shim, feature_store.FeatureStore

---

## File Map

```
feature-mcp/
  rest_api.py                          MODIFY — add 6 new endpoints + 5 Pydantic models
  tests/
    test_rest_api.py                   MODIFY — add tests for new endpoints
    test_e2e_lifecycle.py              CREATE — 15 in-process E2E lifecycle tests

bridgecrew/
  tests/e2e/
    test_feature_mcp.py                CREATE — 3 smoke tests against localhost:8765
```

No changes to `mcp_tools.py`, `feature_store.py`, `server.py`, or `conftest.py`.

---

### Task 1: REST lifecycle endpoints

**Files:**
- Modify: `rest_api.py`
- Modify: `tests/test_rest_api.py`

- [ ] **Step 1: Write failing tests for the 6 new endpoints**

Append to `tests/test_rest_api.py`:

```python
# ── helpers ────────────────────────────────────────────────────────────────
def _enc(path):
    return quote(str(path), safe="")


def _started_fixture(store, tmp_project, session_id="sess-a", name="e2e-feat"):
    """Helper: start a feature via store directly (so tests don't depend on REST start)."""
    now = _now_iso()
    data = {
        "name": name, "status": "active", "session_id": session_id,
        "sessions": [{"session_id": session_id, "session_start": now,
                       "source": "rest", "status": "active"}],
        "milestones": [], "started_at": now, "completed_at": None,
        "total_cost_usd": 0.0, "total_input_tokens": 0, "total_output_tokens": 0,
        "prompt_count": 0,
    }
    store.write_feature(tmp_project, name, data)
    store.register_session(tmp_project, session_id, name)
    return data


# ── POST /api/projects ─────────────────────────────────────────────────────
def test_register_project_new(client, tmp_path):
    c, store, tmp_project = client
    new_dir = tmp_path / "new_proj"
    (new_dir / ".claude" / "features").mkdir(parents=True)
    r = c.post("/api/projects", json={"project_dir": str(new_dir)})
    assert r.status_code == 200
    assert r.json()["status"] == "registered"
    # now recognized by store
    r2 = c.get(f"/api/projects/{_enc(new_dir)}/features")
    assert r2.status_code == 200


def test_register_project_idempotent(client):
    c, store, tmp_project = client
    r1 = c.post("/api/projects", json={"project_dir": str(tmp_project)})
    r2 = c.post("/api/projects", json={"project_dir": str(tmp_project)})
    assert r1.status_code == 200
    assert r2.status_code == 200


# ── POST .../features/{name}/start ────────────────────────────────────────
def test_rest_start_creates_feature(client):
    c, store, tmp_project = client
    r = c.post(
        f"/api/projects/{_enc(tmp_project)}/features/my-feat/start",
        json={"session_id": "sess-1"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "started"
    assert store.get_session_feature(tmp_project, "sess-1")["name"] == "my-feat"


def test_rest_start_conflict(client):
    c, store, tmp_project = client
    _started_fixture(store, tmp_project, "sess-existing", "shared")
    r = c.post(
        f"/api/projects/{_enc(tmp_project)}/features/shared/start",
        json={"session_id": "sess-new"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "conflict"
    assert "conflicting_session_id" in r.json()


def test_rest_start_force(client):
    c, store, tmp_project = client
    _started_fixture(store, tmp_project, "sess-old", "shared")
    r = c.post(
        f"/api/projects/{_enc(tmp_project)}/features/shared/start",
        json={"session_id": "sess-new", "force": True},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "started"
    assert store.get_session_feature(tmp_project, "sess-old") is None


def test_rest_start_unknown_project(client):
    c, store, tmp_project = client
    r = c.post(
        f"/api/projects/{_enc('/nonexistent')}/features/x/start",
        json={"session_id": "s"},
    )
    assert r.status_code == 404


# ── POST .../sessions/{id}/resume ─────────────────────────────────────────
def test_rest_resume_feature(client):
    c, store, tmp_project = client
    _started_fixture(store, tmp_project, "sess-1", "my-feat")
    # complete it first so it can be resumed
    feat = store.get_session_feature(tmp_project, "sess-1")
    feat["status"] = "completed"
    feat["completed_at"] = _now_iso()
    store.write_feature(tmp_project, "my-feat", feat)
    store.unregister_session("sess-1")

    r = c.post(
        f"/api/projects/{_enc(tmp_project)}/sessions/sess-2/resume",
        json={"feature_name": "my-feat"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "resumed"
    assert store.get_session_feature(tmp_project, "sess-2")["name"] == "my-feat"


def test_rest_resume_not_found(client):
    c, store, tmp_project = client
    r = c.post(
        f"/api/projects/{_enc(tmp_project)}/sessions/sess-1/resume",
        json={"feature_name": "ghost"},
    )
    assert r.status_code == 200
    assert "error" in r.json()


# ── POST .../sessions/{id}/complete ───────────────────────────────────────
def test_rest_complete_writes_markdown(client):
    c, store, tmp_project = client
    _started_fixture(store, tmp_project, "sess-1", "done-feat")
    r = c.post(
        f"/api/projects/{_enc(tmp_project)}/sessions/sess-1/complete",
        json={"summary": "Built the thing."},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    md = tmp_project / "features" / "done-feat.md"
    assert md.exists()
    assert "Built the thing." in md.read_text()


def test_rest_complete_unregisters_session(client):
    c, store, tmp_project = client
    _started_fixture(store, tmp_project, "sess-1", "done-feat")
    c.post(
        f"/api/projects/{_enc(tmp_project)}/sessions/sess-1/complete",
        json={"summary": "Done."},
    )
    assert store.get_session_feature(tmp_project, "sess-1") is None


def test_rest_complete_no_active(client):
    c, store, tmp_project = client
    r = c.post(
        f"/api/projects/{_enc(tmp_project)}/sessions/nobody/complete",
        json={"summary": "x"},
    )
    assert r.status_code == 200
    assert "error" in r.json()


# ── POST .../sessions/{id}/discard ────────────────────────────────────────
def test_rest_discard_deletes_json(client):
    c, store, tmp_project = client
    _started_fixture(store, tmp_project, "sess-1", "dead-feat")
    r = c.post(f"/api/projects/{_enc(tmp_project)}/sessions/sess-1/discard")
    assert r.status_code == 200
    assert r.json()["status"] == "discarded"
    # JSON file removed → GET /features returns empty
    r2 = c.get(f"/api/projects/{_enc(tmp_project)}/features")
    assert r2.json() == []


def test_rest_discard_archives_markdown(client):
    c, store, tmp_project = client
    _started_fixture(store, tmp_project, "sess-1", "dead-feat")
    md = tmp_project / "features" / "dead-feat.md"
    md.parent.mkdir(exist_ok=True)
    md.write_text("# dead-feat\nsome content")
    c.post(f"/api/projects/{_enc(tmp_project)}/sessions/sess-1/discard")
    assert not md.exists()
    assert (tmp_project / "features" / "_archived" / "dead-feat.md").exists()


# ── POST .../sessions/{id}/milestone ──────────────────────────────────────
def test_rest_milestone_added(client):
    c, store, tmp_project = client
    _started_fixture(store, tmp_project, "sess-1", "wip")
    r = c.post(
        f"/api/projects/{_enc(tmp_project)}/sessions/sess-1/milestone",
        json={"text": "reached checkpoint"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "added"
    feat = store.read_feature(tmp_project, "wip")
    assert feat["milestones"][0]["text"] == "reached checkpoint"


def test_rest_milestone_no_active(client):
    c, store, tmp_project = client
    r = c.post(
        f"/api/projects/{_enc(tmp_project)}/sessions/nobody/milestone",
        json={"text": "x"},
    )
    assert r.status_code == 200
    assert "error" in r.json()
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd M:\feature-mcp
.venv\Scripts\activate
pytest tests/test_rest_api.py::test_register_project_new -v
```

Expected: `FAILED` — `404 Not Found` or `AttributeError` (endpoints not defined yet).

- [ ] **Step 3: Implement the 6 new endpoints in `rest_api.py`**

Replace the full contents of `rest_api.py` with:

```python
# rest_api.py
import json as _json
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from urllib.parse import unquote

from feature_store import FeatureStore, _now_iso
from mcp_tools import _conflict_response, _abandon_session, _render_summary


class CostPayload(BaseModel):
    cost_usd: float
    input_tokens: int
    output_tokens: int


class RegisterProjectPayload(BaseModel):
    project_dir: str


class StartFeaturePayload(BaseModel):
    session_id: str
    subdir: str | None = None
    force: bool = False


class ResumeFeaturePayload(BaseModel):
    feature_name: str
    force: bool = False


class CompleteFeaturePayload(BaseModel):
    summary: str


class MilestonePayload(BaseModel):
    text: str


def create_api_router(store: FeatureStore) -> APIRouter:
    router = APIRouter()

    # ── Existing endpoints ─────────────────────────────────────────────────

    @router.get("/projects/{encoded_path:path}/features")
    def get_features(encoded_path: str):
        project_dir_str = unquote(encoded_path)
        try:
            pdir = store.ensure_project_dir(project_dir_str)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"Unknown project: {project_dir_str}")
        return store.list_features(pdir)

    @router.post("/projects/{encoded_path:path}/sessions/{session_id}/cost")
    def post_cost(encoded_path: str, session_id: str, body: CostPayload):
        project_dir_str = unquote(encoded_path)
        try:
            pdir = store.ensure_project_dir(project_dir_str)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"Unknown project: {project_dir_str}")
        data = store.get_session_feature(pdir, session_id)
        if not data:
            return {"status": "no_active_feature"}
        store.accumulate_cost(
            pdir, data["name"],
            cost_usd=body.cost_usd,
            input_tokens=body.input_tokens,
            output_tokens=body.output_tokens,
        )
        return {"status": "ok"}

    @router.post("/admin/restart")
    def post_restart():
        os._exit(42)

    # ── Project registration ───────────────────────────────────────────────

    @router.post("/projects")
    def register_project(body: RegisterProjectPayload):
        p = Path(body.project_dir)
        if p not in store._projects:
            store._projects.append(p)
        (p / ".claude" / "features").mkdir(parents=True, exist_ok=True)
        return {"status": "registered", "project_dir": str(p)}

    # ── Lifecycle endpoints ────────────────────────────────────────────────

    @router.post("/projects/{encoded_path:path}/features/{feature_name}/start")
    def post_start_feature(encoded_path: str, feature_name: str, body: StartFeaturePayload):
        project_dir_str = unquote(encoded_path)
        try:
            pdir = store.ensure_project_dir(project_dir_str)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"Unknown project: {project_dir_str}")

        session_id = body.session_id

        # Auto-complete any feature already active for this session
        existing = store.get_session_feature(pdir, session_id)
        if existing:
            existing["status"] = "completed"
            existing["completed_at"] = _now_iso()
            for s in existing.get("sessions", []):
                if s.get("session_id") == session_id:
                    s["status"] = "completed"
            store.write_feature(pdir, existing["name"], existing)
            store.unregister_session(session_id)

        # Conflict check
        conflict_sid = store.get_active_session_for_feature(pdir, feature_name)
        if conflict_sid and conflict_sid != session_id:
            if not body.force:
                return _json.loads(_conflict_response(store, pdir, feature_name, conflict_sid))
            _abandon_session(store, pdir, feature_name, conflict_sid)

        now = _now_iso()
        existing_data = store.read_feature(pdir, feature_name) or {}
        feature_data = {
            "name": feature_name,
            "status": "active",
            "session_id": session_id,
            "description": existing_data.get("description", ""),
            "sessions": existing_data.get("sessions", []) + [
                {"session_id": session_id, "session_start": now,
                 "source": "rest", "status": "active"}
            ],
            "milestones": existing_data.get("milestones", []),
            "started_at": existing_data.get("started_at") or now,
            "completed_at": None,
            "total_cost_usd": existing_data.get("total_cost_usd", 0.0),
            "total_input_tokens": existing_data.get("total_input_tokens", 0),
            "total_output_tokens": existing_data.get("total_output_tokens", 0),
            "prompt_count": existing_data.get("prompt_count", 0),
        }
        store.write_feature(pdir, feature_name, feature_data)
        store.register_session(pdir, session_id, feature_name)
        return {"status": "started", "feature_name": feature_name}

    @router.post("/projects/{encoded_path:path}/sessions/{session_id}/resume")
    def post_resume_feature(encoded_path: str, session_id: str, body: ResumeFeaturePayload):
        project_dir_str = unquote(encoded_path)
        try:
            pdir = store.ensure_project_dir(project_dir_str)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"Unknown project: {project_dir_str}")

        data = store.read_feature(pdir, body.feature_name)
        if not data:
            return {"error": f"Feature '{body.feature_name}' not found"}

        conflict_sid = store.get_active_session_for_feature(pdir, body.feature_name)
        if conflict_sid and conflict_sid != session_id:
            if not body.force:
                return _json.loads(_conflict_response(store, pdir, body.feature_name, conflict_sid))
            _abandon_session(store, pdir, body.feature_name, conflict_sid)

        now = _now_iso()
        data["status"] = "active"
        data["completed_at"] = None
        data["session_id"] = session_id
        data.setdefault("sessions", []).append(
            {"session_id": session_id, "session_start": now,
             "source": "rest", "status": "active"}
        )
        store.write_feature(pdir, body.feature_name, data)
        store.register_session(pdir, session_id, body.feature_name)
        return {"status": "resumed", "feature_name": body.feature_name}

    @router.post("/projects/{encoded_path:path}/sessions/{session_id}/complete")
    def post_complete_feature(encoded_path: str, session_id: str, body: CompleteFeaturePayload):
        project_dir_str = unquote(encoded_path)
        try:
            pdir = store.ensure_project_dir(project_dir_str)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"Unknown project: {project_dir_str}")

        data = store.get_session_feature(pdir, session_id)
        if not data:
            return {"error": "No active feature for this session"}

        name = data["name"]
        now = _now_iso()
        data["status"] = "completed"
        data["completed_at"] = now
        for s in data.get("sessions", []):
            if s.get("session_id") == session_id:
                s["status"] = "completed"
        store.write_feature(pdir, name, data)
        store.unregister_session(session_id)

        md_path = pdir / "features" / f"{name}.md"
        md_path.parent.mkdir(exist_ok=True)
        md_path.write_text(_render_summary(data, body.summary), encoding="utf-8")
        return {"status": "completed", "feature_name": name}

    @router.post("/projects/{encoded_path:path}/sessions/{session_id}/discard")
    def post_discard_feature(encoded_path: str, session_id: str):
        project_dir_str = unquote(encoded_path)
        try:
            pdir = store.ensure_project_dir(project_dir_str)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"Unknown project: {project_dir_str}")

        data = store.get_session_feature(pdir, session_id)
        if not data:
            return {"error": "No active feature for this session"}

        name = data["name"]
        store.unregister_session(session_id)

        # Archive markdown if present
        md_path = pdir / "features" / f"{name}.md"
        if md_path.exists():
            archive = pdir / "features" / "_archived"
            archive.mkdir(exist_ok=True)
            md_path.rename(archive / f"{name}.md")

        # Delete JSON entirely (clean removal; use MCP feature_discard for soft-delete)
        json_path = store._feature_path(pdir, name)
        json_path.unlink(missing_ok=True)

        return {"status": "discarded", "feature_name": name}

    @router.post("/projects/{encoded_path:path}/sessions/{session_id}/milestone")
    def post_milestone(encoded_path: str, session_id: str, body: MilestonePayload):
        project_dir_str = unquote(encoded_path)
        try:
            pdir = store.ensure_project_dir(project_dir_str)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"Unknown project: {project_dir_str}")

        data = store.get_session_feature(pdir, session_id)
        if not data:
            return {"error": "No active feature for this session"}

        milestone = {"timestamp": _now_iso(), "session_id": session_id, "text": body.text}
        data.setdefault("milestones", []).append(milestone)
        store.write_feature(pdir, data["name"], data)
        return {"status": "added", "milestone": milestone}

    return router
```

- [ ] **Step 4: Run all REST API tests**

```
pytest tests/test_rest_api.py -v
```

Expected: All tests pass. If any fail, check the error message and fix the handler — common issues are wrong URL patterns or missing imports.

- [ ] **Step 5: Commit**

```
git add rest_api.py tests/test_rest_api.py
git commit -m "feat: add REST lifecycle endpoints (start, resume, complete, discard, milestone, register)"
```

---

### Task 2: In-process E2E lifecycle tests

**Files:**
- Create: `tests/test_e2e_lifecycle.py`

- [ ] **Step 1: Create `tests/test_e2e_lifecycle.py` with the fixture and all 15 tests**

```python
# tests/test_e2e_lifecycle.py
"""
In-process E2E lifecycle tests.

Uses FakeMCP (same shim as test_tools.py) for MCP tool calls and
FastAPI TestClient for REST state verification — both sharing one
FeatureStore instance, so state is always consistent.
"""
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from urllib.parse import quote

from feature_store import FeatureStore, _now_iso
from mcp_tools import register_tools
from rest_api import create_api_router


# ── FakeMCP shim ──────────────────────────────────────────────────────────

class FakeMCP:
    def __init__(self):
        self._tools: dict = {}

    def tool(self):
        def decorator(fn):
            self._tools[fn.__name__] = fn
            return fn
        return decorator

    def call(self, name, **kwargs):
        return self._tools[name](**kwargs)


# ── Shared fixture ────────────────────────────────────────────────────────

@pytest.fixture
def e2e(tmp_project):
    store = FeatureStore([str(tmp_project)])
    mcp = FakeMCP()
    register_tools(mcp, store)
    app = FastAPI()
    app.include_router(create_api_router(store), prefix="/api")
    client = TestClient(app)
    return mcp, store, client, tmp_project


def _enc(path):
    return quote(str(path), safe="")


# ── TestHappyPath ─────────────────────────────────────────────────────────

class TestHappyPath:
    def test_start_creates_feature(self, e2e):
        mcp, store, client, proj = e2e
        result = json.loads(mcp.call("feature_start",
                                     project_dir=str(proj),
                                     session_id="sess-1",
                                     name="my-feat"))
        assert result["status"] == "started"
        feat = store.get_session_feature(proj, "sess-1")
        assert feat is not None
        assert feat["name"] == "my-feat"
        assert (proj / ".claude" / "features" / "my_feat.json").exists()

    def test_milestone_recorded(self, e2e):
        mcp, store, client, proj = e2e
        mcp.call("feature_start", project_dir=str(proj), session_id="sess-1", name="my-feat")
        result = json.loads(mcp.call("feature_add_milestone",
                                     project_dir=str(proj),
                                     session_id="sess-1",
                                     text="Wired up the API"))
        assert result["status"] == "added"
        feat = store.read_feature(proj, "my-feat")
        assert len(feat["milestones"]) == 1
        assert feat["milestones"][0]["text"] == "Wired up the API"
        assert "timestamp" in feat["milestones"][0]

    def test_rest_returns_active_feature(self, e2e):
        mcp, store, client, proj = e2e
        mcp.call("feature_start", project_dir=str(proj), session_id="sess-1", name="my-feat")
        r = client.get(f"/api/projects/{_enc(proj)}/features")
        assert r.status_code == 200
        features = r.json()
        assert any(f["name"] == "my-feat" and f["status"] == "active" for f in features)

    def test_complete_writes_markdown(self, e2e):
        mcp, store, client, proj = e2e
        mcp.call("feature_start", project_dir=str(proj), session_id="sess-1", name="my-feat")
        result = json.loads(mcp.call("feature_complete",
                                     project_dir=str(proj),
                                     session_id="sess-1",
                                     summary="Built the full pipeline."))
        assert result["status"] == "completed"
        md = proj / "features" / "my-feat.md"
        assert md.exists()
        content = md.read_text()
        assert "Built the full pipeline." in content
        assert "# my-feat" in content

    def test_complete_unregisters_session(self, e2e):
        mcp, store, client, proj = e2e
        mcp.call("feature_start", project_dir=str(proj), session_id="sess-1", name="my-feat")
        mcp.call("feature_complete", project_dir=str(proj), session_id="sess-1", summary="Done.")
        assert store.get_session_feature(proj, "sess-1") is None

    def test_rest_returns_completed_feature(self, e2e):
        mcp, store, client, proj = e2e
        mcp.call("feature_start", project_dir=str(proj), session_id="sess-1", name="my-feat")
        mcp.call("feature_complete", project_dir=str(proj), session_id="sess-1", summary="Done.")
        r = client.get(f"/api/projects/{_enc(proj)}/features")
        features = r.json()
        assert any(f["name"] == "my-feat" and f["status"] == "completed" for f in features)


# ── TestConflictResolution ────────────────────────────────────────────────

class TestConflictResolution:
    def test_concurrent_start_returns_conflict(self, e2e):
        mcp, store, client, proj = e2e
        mcp.call("feature_start", project_dir=str(proj), session_id="sess-a", name="shared")
        result = json.loads(mcp.call("feature_start",
                                     project_dir=str(proj),
                                     session_id="sess-b",
                                     name="shared"))
        assert result["status"] == "conflict"
        assert result["conflicting_session_id"] == "sess-a"
        assert "recommendation" in result

    def test_force_abandons_old_session(self, e2e):
        mcp, store, client, proj = e2e
        mcp.call("feature_start", project_dir=str(proj), session_id="sess-a", name="shared")
        result = json.loads(mcp.call("feature_start",
                                     project_dir=str(proj),
                                     session_id="sess-b",
                                     name="shared",
                                     force=True))
        assert result["status"] == "started"
        assert store.get_session_feature(proj, "sess-a") is None
        feat = store.read_feature(proj, "shared")
        statuses = [s["status"] for s in feat["sessions"]]
        assert "abandoned" in statuses

    def test_forced_session_active(self, e2e):
        mcp, store, client, proj = e2e
        mcp.call("feature_start", project_dir=str(proj), session_id="sess-a", name="shared")
        mcp.call("feature_start", project_dir=str(proj), session_id="sess-b", name="shared", force=True)
        feat = store.get_session_feature(proj, "sess-b")
        assert feat is not None
        assert feat["name"] == "shared"


# ── TestResumePath ────────────────────────────────────────────────────────

class TestResumePath:
    def test_resume_completed_feature(self, e2e):
        mcp, store, client, proj = e2e
        mcp.call("feature_start", project_dir=str(proj), session_id="sess-1", name="old-feat")
        mcp.call("feature_complete", project_dir=str(proj), session_id="sess-1", summary="v1 done.")
        result = json.loads(mcp.call("feature_resume",
                                     project_dir=str(proj),
                                     session_id="sess-2",
                                     feature_name="old-feat"))
        assert result["status"] == "resumed"
        assert store.get_session_feature(proj, "sess-2")["name"] == "old-feat"

    def test_milestone_after_resume(self, e2e):
        mcp, store, client, proj = e2e
        mcp.call("feature_start", project_dir=str(proj), session_id="sess-1", name="old-feat")
        mcp.call("feature_complete", project_dir=str(proj), session_id="sess-1", summary="v1 done.")
        mcp.call("feature_resume", project_dir=str(proj), session_id="sess-2", feature_name="old-feat")
        mcp.call("feature_add_milestone", project_dir=str(proj), session_id="sess-2", text="v2 checkpoint")
        feat = store.read_feature(proj, "old-feat")
        assert any(m["text"] == "v2 checkpoint" for m in feat["milestones"])

    def test_complete_after_resume(self, e2e):
        mcp, store, client, proj = e2e
        mcp.call("feature_start", project_dir=str(proj), session_id="sess-1", name="old-feat")
        mcp.call("feature_complete", project_dir=str(proj), session_id="sess-1", summary="v1 done.")
        mcp.call("feature_resume", project_dir=str(proj), session_id="sess-2", feature_name="old-feat")
        result = json.loads(mcp.call("feature_complete",
                                     project_dir=str(proj),
                                     session_id="sess-2",
                                     summary="v2 complete."))
        assert result["status"] == "completed"
        feat = store.read_feature(proj, "old-feat")
        assert feat["status"] == "completed"
        md = proj / "features" / "old-feat.md"
        assert "v2 complete." in md.read_text()


# ── TestDiscardPath ───────────────────────────────────────────────────────

class TestDiscardPath:
    def test_discard_marks_discarded(self, e2e):
        mcp, store, client, proj = e2e
        mcp.call("feature_start", project_dir=str(proj), session_id="sess-1", name="dead-feat")
        result = json.loads(mcp.call("feature_discard",
                                     project_dir=str(proj),
                                     session_id="sess-1"))
        assert result["status"] == "discarded"
        feat = store.read_feature(proj, "dead-feat")
        assert feat["status"] == "discarded"
        assert store.get_session_feature(proj, "sess-1") is None

    def test_discard_archives_doc(self, e2e):
        mcp, store, client, proj = e2e
        mcp.call("feature_start", project_dir=str(proj), session_id="sess-1", name="dead-feat")
        md = proj / "features" / "dead-feat.md"
        md.parent.mkdir(exist_ok=True)
        md.write_text("# dead-feat\nsome content")
        mcp.call("feature_discard", project_dir=str(proj), session_id="sess-1")
        assert not md.exists()
        assert (proj / "features" / "_archived" / "dead-feat.md").exists()

    def test_rest_discard_removes_feature(self, e2e):
        mcp, store, client, proj = e2e
        # Start via MCP, discard via REST (REST endpoint deletes JSON entirely)
        mcp.call("feature_start", project_dir=str(proj), session_id="sess-1", name="dead-feat")
        r = client.post(f"/api/projects/{_enc(proj)}/sessions/sess-1/discard")
        assert r.status_code == 200
        assert r.json()["status"] == "discarded"
        r2 = client.get(f"/api/projects/{_enc(proj)}/features")
        assert r2.json() == []
```

- [ ] **Step 2: Run the new tests**

```
pytest tests/test_e2e_lifecycle.py -v
```

Expected: All 15 tests pass. If a test fails, read the error carefully — the most common issue is a mismatched feature name (the store uses `to_snake()` for the filename but `data["name"]` stores the original name).

- [ ] **Step 3: Run the full test suite to check for regressions**

```
pytest -v
```

Expected: All 51+ tests pass (36 original + ~15 new). No regressions.

- [ ] **Step 4: Commit**

```
git add tests/test_e2e_lifecycle.py
git commit -m "test: add in-process E2E lifecycle tests for all four lifecycle paths"
```

---

### Task 3: Real-server smoke tests

**Files:**
- Create: `M:\bridgecrew\tests\e2e\test_feature_mcp.py`

These tests run only when `localhost:8765` is reachable. They are skipped automatically otherwise — safe to run in CI without the server.

- [ ] **Step 1: Create `M:\bridgecrew\tests\e2e\test_feature_mcp.py`**

```python
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
```

- [ ] **Step 2: Run the smoke tests with the server stopped (verify skip works)**

```
cd M:\bridgecrew
pytest tests/e2e/test_feature_mcp.py -v
```

Expected: All 3 tests show `SKIPPED` with `"feature-mcp server not running on localhost:8765"`. If they show `FAILED` instead, check that `_server_available()` handles the connection error correctly.

- [ ] **Step 3: Start the feature-mcp server, then run the smoke tests**

In a separate terminal:
```
M:\feature-mcp\start.bat
```

Wait for `[feature-mcp] Starting on http://127.0.0.1:8765`, then:

```
cd M:\bridgecrew
pytest tests/e2e/test_feature_mcp.py -v
```

Expected:
```
tests/e2e/test_feature_mcp.py::test_live_start_registers_feature PASSED
tests/e2e/test_feature_mcp.py::test_live_lifecycle_complete PASSED
tests/e2e/test_feature_mcp.py::test_server_rejects_unknown_project PASSED
```

If `test_live_lifecycle_complete` fails on the markdown check, verify that `tmp_path` is a path the server can write to (it should be — it's in the system temp directory).

- [ ] **Step 4: Run the full bridgecrew test suite to check for regressions**

```
cd M:\bridgecrew
pytest tests/ -v --ignore=tests/e2e/test_feature_mcp.py
```

Expected: All existing tests pass. The smoke tests are excluded here since the server may not be running in CI.

- [ ] **Step 5: Commit in bridgecrew repo**

```
cd M:\bridgecrew
git add tests/e2e/test_feature_mcp.py
git commit -m "test: add feature-mcp smoke tests against localhost:8765"
```

---

## Self-Review

**Spec coverage:**
- Part 1 (REST endpoints): ✓ Task 1 implements all 6 endpoints with tests
- Part 2 (in-process E2E): ✓ Task 2 covers all 4 test groups (15 tests)
- Part 3 (smoke test): ✓ Task 3 covers connectivity, full lifecycle, rejection
- Skip condition: ✓ `skip_no_server` decorator handles server-down case
- `live_project` fixture: ✓ registers temp project, yields client, teardown discards

**Placeholder scan:** No TBDs. All code blocks are complete and runnable.

**Type consistency:**
- `store.get_session_feature(proj, session_id)` → `dict | None` — consistent throughout
- `store.read_feature(proj, name)` → `dict | None` — consistent
- `mcp.call("feature_start", ...)` → `str` (JSON) — decoded with `json.loads()` in tests ✓
- `store._feature_path(pdir, name)` used in discard REST handler — this is a store method that exists in `feature_store.py` (defined on line 49) ✓
- Feature name in markdown path: `proj / "features" / "my-feat.md"` — matches `_render_summary` which uses `data["name"]` directly (not snake-cased) ✓
- JSON filename: `to_snake("my-feat")` = `"my_feat"` → `my_feat.json` — `(proj / ".claude" / "features" / "my_feat.json").exists()` in `test_start_creates_feature` ✓
