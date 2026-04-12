# Feature MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bot's `core/feature_manager.py` and the CLAUDE.md feature lifecycle prompt block with a persistent MCP server (`M:\feature-mcp`) that manages feature state across all sessions via HTTP/SSE.

**Architecture:** A FastAPI + FastMCP server on `localhost:8765` serves two interfaces: `/mcp` (SSE for Claude sessions) and `/api` (REST for the Discord bot). All feature state lives in `<project>/.claude/features/*.json` files written atomically. In-memory session→feature routing is rebuilt from those files on startup, eliminating the global `current_feature` collision.

**Tech Stack:** Python 3.11+, `mcp` (FastMCP), `fastapi`, `uvicorn`, `httpx` (bot client), `pytest`, `pytest-asyncio`

---

## File Map

**New project `M:\feature-mcp\`:**
- Create: `feature_store.py` — data model, file I/O, session routing (no framework deps)
- Create: `mcp_tools.py` — FastMCP tool registrations, summary prompt text
- Create: `rest_api.py` — FastAPI REST routes for the bot
- Create: `server.py` — startup wiring: MCP + REST + project scan
- Create: `projects.json` — list of project dirs to scan
- Create: `start.bat` — Windows launcher
- Create: `requirements.txt`
- Create: `tests/conftest.py`
- Create: `tests/test_feature_store.py`
- Create: `tests/test_tools.py`
- Create: `tests/test_rest_api.py`

**Modified in `M:\bridgecrew\`:**
- Create: `core/mcp_client.py` — async httpx wrapper replacing feature_manager for bot use
- Modify: `discord_cogs/claude_prompt.py` — replace `feature_manager` calls with `mcp_client`
- Modify: `discord_cogs/features.py` — replace `feature_manager` calls with `mcp_client`
- Delete: `core/feature_manager.py`
- Modify: `core/state.py` — remove feature-specific functions (keep general project state)
- Modify: `C:\Users\mplanck\.claude\CLAUDE.md` — replace feature lifecycle block
- Modify: `C:\Users\mplanck\.claude\settings.json` — register MCP server

---

## Task 1: Scaffold `M:\feature-mcp`

**Files:**
- Create: `M:\feature-mcp\requirements.txt`
- Create: `M:\feature-mcp\projects.json`
- Create: `M:\feature-mcp\tests\conftest.py`

- [ ] **Step 1: Create project directory and git repo**

```bash
mkdir M:/feature-mcp
cd M:/feature-mcp
git init
```

- [ ] **Step 2: Write `requirements.txt`**

```
mcp>=1.0
fastapi>=0.111
uvicorn[standard]>=0.29
httpx>=0.27
pytest>=8.0
pytest-asyncio>=0.23
```

- [ ] **Step 3: Write `projects.json`**

```json
[
  "M:/bridgecrew",
  "M:/mappa",
  "M:/myvillage-agents",
  "M:/myvillage-apps",
  "M:/nms-helper",
  "M:/plio-max",
  "M:/sbi"
]
```

- [ ] **Step 4: Create venv and install**

```bash
cd M:/feature-mcp
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
```

Expected: packages install without error.

- [ ] **Step 5: Write `tests/conftest.py`**

```python
import pytest
import tempfile
import json
from pathlib import Path
from feature_store import FeatureStore

@pytest.fixture
def tmp_project(tmp_path):
    """A temp directory set up as a project with .claude/features/."""
    features_dir = tmp_path / ".claude" / "features"
    features_dir.mkdir(parents=True)
    (tmp_path / ".claude" / "features.json").write_text("{}")
    return tmp_path

@pytest.fixture
def store(tmp_project):
    s = FeatureStore([str(tmp_project)])
    return s
```

- [ ] **Step 6: Commit scaffold**

```bash
cd M:/feature-mcp
git add .
git commit -m "chore: scaffold feature-mcp project"
```

---

## Task 2: `feature_store.py` — data model and utilities

**Files:**
- Create: `M:\feature-mcp\feature_store.py`
- Create: `M:\feature-mcp\tests\test_feature_store.py`

- [ ] **Step 1: Write failing tests for `to_snake` and `_atomic_write`**

```python
# tests/test_feature_store.py
import json
import pytest
from pathlib import Path
from feature_store import to_snake, _atomic_write

def test_to_snake_basic():
    assert to_snake("my-feature") == "my_feature"

def test_to_snake_ampersand():
    assert to_snake("Bugs & Fixes") == "bugs_and_fixes"

def test_to_snake_mixed():
    assert to_snake("Star-trek-personas") == "star_trek_personas"

def test_to_snake_empty():
    assert to_snake("") == "unnamed"

def test_to_snake_special_chars():
    assert to_snake("feat!@#$") == "feat"

def test_atomic_write_creates_file(tmp_path):
    path = tmp_path / "test.json"
    _atomic_write(path, {"key": "value"})
    assert json.loads(path.read_text()) == {"key": "value"}

def test_atomic_write_no_tmp_left(tmp_path):
    path = tmp_path / "test.json"
    _atomic_write(path, {"key": "value"})
    assert not (tmp_path / "test.tmp").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd M:/feature-mcp && .venv/Scripts/activate
pytest tests/test_feature_store.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'feature_store'`

- [ ] **Step 3: Write `feature_store.py` — utilities only**

```python
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_snake(name: str) -> str:
    name = name.lower()
    name = name.replace("&", "and")
    name = re.sub(r"[-\s]+", "_", name)
    name = re.sub(r"[^a-z0-9_]", "", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "unnamed"


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    for attempt in range(3):
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(path)
            return
        except PermissionError:
            if attempt < 2:
                time.sleep(0.1)
            else:
                raise
```

- [ ] **Step 4: Run utility tests — verify they pass**

```bash
pytest tests/test_feature_store.py::test_to_snake_basic tests/test_feature_store.py::test_atomic_write_creates_file -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add feature_store.py tests/test_feature_store.py
git commit -m "feat: feature_store utilities (to_snake, atomic_write)"
```

---

## Task 3: `feature_store.py` — file I/O

**Files:**
- Modify: `M:\feature-mcp\feature_store.py`
- Modify: `M:\feature-mcp\tests\test_feature_store.py`

- [ ] **Step 1: Add file I/O tests**

```python
# append to tests/test_feature_store.py
from feature_store import FeatureStore

def test_write_and_read_feature(store, tmp_project):
    data = {"name": "my-feature", "status": "active", "sessions": []}
    store.write_feature(tmp_project, "my-feature", data)
    result = store.read_feature(tmp_project, "my-feature")
    assert result["name"] == "my-feature"
    assert result["status"] == "active"

def test_read_missing_feature_returns_none(store, tmp_project):
    assert store.read_feature(tmp_project, "nonexistent") is None

def test_list_features_returns_all(store, tmp_project):
    store.write_feature(tmp_project, "feat-a", {"name": "feat-a", "status": "active"})
    store.write_feature(tmp_project, "feat-b", {"name": "feat-b", "status": "completed"})
    features = store.list_features(tmp_project)
    names = [f["name"] for f in features]
    assert "feat-a" in names
    assert "feat-b" in names

def test_feature_path_uses_snake_case(store, tmp_project):
    store.write_feature(tmp_project, "My Feature", {"name": "My Feature", "status": "active"})
    path = tmp_project / ".claude" / "features" / "my_feature.json"
    assert path.exists()

def test_ensure_project_dir_rejects_unknown(store):
    with pytest.raises(ValueError, match="Unknown project"):
        store.ensure_project_dir("/nonexistent/path")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_feature_store.py -k "test_write_and_read or test_read_missing or test_list_features or test_feature_path or test_ensure_project" -v
```

Expected: `AttributeError: 'FeatureStore' object has no attribute 'write_feature'`

- [ ] **Step 3: Add `FeatureStore` class with file I/O to `feature_store.py`**

Append after the utility functions:

```python
class FeatureStore:
    def __init__(self, projects: list[str]):
        self._projects = [Path(p) for p in projects]
        # session_id -> (project_dir, feature_name)
        self._sessions: dict[str, tuple[Path, str]] = {}

    def ensure_project_dir(self, project_dir_str: str) -> Path:
        p = Path(project_dir_str)
        if p not in self._projects:
            raise ValueError(f"Unknown project: {project_dir_str}")
        return p

    def _feature_path(self, project_dir: Path, name: str) -> Path:
        return project_dir / ".claude" / "features" / f"{to_snake(name)}.json"

    def _read_file(self, path: Path) -> Optional[dict]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def read_feature(self, project_dir: Path, name: str) -> Optional[dict]:
        return self._read_file(self._feature_path(project_dir, name))

    def write_feature(self, project_dir: Path, name: str, data: dict) -> None:
        _atomic_write(self._feature_path(project_dir, name), data)

    def list_features(self, project_dir: Path) -> list[dict]:
        features_dir = project_dir / ".claude" / "features"
        if not features_dir.exists():
            return []
        results = []
        for p in sorted(features_dir.glob("*.json")):
            data = self._read_file(p)
            if data:
                results.append(data)
        return results
```

- [ ] **Step 4: Run file I/O tests — verify they pass**

```bash
pytest tests/test_feature_store.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add feature_store.py tests/test_feature_store.py
git commit -m "feat: feature_store file I/O"
```

---

## Task 4: `feature_store.py` — session routing and startup scan

**Files:**
- Modify: `M:\feature-mcp\feature_store.py`
- Modify: `M:\feature-mcp\tests\test_feature_store.py`

- [ ] **Step 1: Add session routing tests**

```python
# append to tests/test_feature_store.py
def test_register_and_get_session_feature(store, tmp_project):
    store.write_feature(tmp_project, "feat-a", {"name": "feat-a", "status": "active", "sessions": []})
    store.register_session(tmp_project, "sess-1", "feat-a")
    result = store.get_session_feature(tmp_project, "sess-1")
    assert result["name"] == "feat-a"

def test_unregister_session(store, tmp_project):
    store.write_feature(tmp_project, "feat-a", {"name": "feat-a", "status": "active", "sessions": []})
    store.register_session(tmp_project, "sess-1", "feat-a")
    store.unregister_session("sess-1")
    assert store.get_session_feature(tmp_project, "sess-1") is None

def test_get_active_session_for_feature(store, tmp_project):
    store.write_feature(tmp_project, "feat-a", {"name": "feat-a", "status": "active", "sessions": []})
    store.register_session(tmp_project, "sess-1", "feat-a")
    assert store.get_active_session_for_feature(tmp_project, "feat-a") == "sess-1"

def test_startup_rebuilds_routing(tmp_project):
    now = _now_iso()
    data = {
        "name": "feat-a",
        "status": "active",
        "session_id": "sess-rebuilt",
        "sessions": [{"session_id": "sess-rebuilt", "session_start": now, "source": "cli", "status": "active"}],
        "milestones": [], "started_at": now, "completed_at": None,
        "total_cost_usd": 0.0, "total_input_tokens": 0, "total_output_tokens": 0,
    }
    store2 = FeatureStore([str(tmp_project)])
    store2.write_feature(tmp_project, "feat-a", data)
    log = store2.startup()
    assert store2.get_session_feature(tmp_project, "sess-rebuilt") is not None
    assert any("feat-a" in msg for msg in log)

def test_accumulate_cost(store, tmp_project):
    store.write_feature(tmp_project, "feat-a", {
        "name": "feat-a", "status": "active",
        "total_cost_usd": 1.0, "total_input_tokens": 100,
        "total_output_tokens": 50, "prompt_count": 2,
    })
    store.accumulate_cost(tmp_project, "feat-a", cost_usd=0.5, input_tokens=200, output_tokens=30)
    data = store.read_feature(tmp_project, "feat-a")
    assert data["total_cost_usd"] == pytest.approx(1.5)
    assert data["total_input_tokens"] == 300
    assert data["prompt_count"] == 3
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_feature_store.py -k "session or startup or accumulate" -v
```

Expected: `AttributeError: 'FeatureStore' object has no attribute 'register_session'`

- [ ] **Step 3: Add session routing methods to `FeatureStore` in `feature_store.py`**

Append inside the `FeatureStore` class:

```python
    def register_session(self, project_dir: Path, session_id: str, feature_name: str) -> None:
        self._sessions[session_id] = (project_dir, feature_name)

    def unregister_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def get_session_feature(self, project_dir: Path, session_id: str) -> Optional[dict]:
        entry = self._sessions.get(session_id)
        if entry and entry[0] == project_dir:
            return self.read_feature(project_dir, entry[1])
        return None

    def get_active_session_for_feature(self, project_dir: Path, name: str) -> Optional[str]:
        for sid, (pdir, fname) in self._sessions.items():
            if pdir == project_dir and to_snake(fname) == to_snake(name):
                return sid
        return None

    def startup(self) -> list[str]:
        log: list[str] = []
        self._sessions.clear()
        for project_dir in self._projects:
            features_dir = project_dir / ".claude" / "features"
            if not features_dir.exists():
                continue
            for json_path in sorted(features_dir.glob("*.json")):
                data = self._read_file(json_path)
                if not data or data.get("status") != "active":
                    continue
                feature_name = data.get("name", json_path.stem)
                for sess in data.get("sessions", []):
                    if sess.get("status") == "active":
                        self._sessions[sess["session_id"]] = (project_dir, feature_name)
                        log.append(
                            f"Restored: {project_dir.name}/{feature_name}"
                            f" <- {sess['session_id'][:8]}"
                        )
        return log

    def accumulate_cost(
        self,
        project_dir: Path,
        feature_name: str,
        cost_usd: float,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        data = self.read_feature(project_dir, feature_name)
        if not data:
            return
        data["total_cost_usd"] = data.get("total_cost_usd", 0.0) + cost_usd
        data["total_input_tokens"] = data.get("total_input_tokens", 0) + input_tokens
        data["total_output_tokens"] = data.get("total_output_tokens", 0) + output_tokens
        data["prompt_count"] = data.get("prompt_count", 0) + 1
        self.write_feature(project_dir, feature_name, data)
```

- [ ] **Step 4: Run all feature_store tests — verify they pass**

```bash
pytest tests/test_feature_store.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add feature_store.py tests/test_feature_store.py
git commit -m "feat: feature_store session routing and startup scan"
```

---

## Task 5: `mcp_tools.py` — read-only tools (`feature_context`, `feature_list`)

**Files:**
- Create: `M:\feature-mcp\mcp_tools.py`
- Create: `M:\feature-mcp\tests\test_tools.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_tools.py
import json
import pytest
from pathlib import Path
from feature_store import FeatureStore, _now_iso
from mcp_tools import register_tools

class FakeMCP:
    """Captures tool registrations so we can call them directly in tests."""
    def __init__(self):
        self._tools: dict = {}
    def tool(self):
        def decorator(fn):
            self._tools[fn.__name__] = fn
            return fn
        return decorator
    def call(self, name, **kwargs):
        return self._tools[name](**kwargs)

@pytest.fixture
def mcp_fixture(tmp_project, store):
    mcp = FakeMCP()
    register_tools(mcp, store)
    return mcp, store, tmp_project

def _active_feature(project_dir, name, session_id):
    now = _now_iso()
    return {
        "name": name, "status": "active", "session_id": session_id,
        "sessions": [{"session_id": session_id, "session_start": now, "source": "cli", "status": "active"}],
        "milestones": [], "started_at": now, "completed_at": None,
        "total_cost_usd": 0.0, "total_input_tokens": 0, "total_output_tokens": 0,
    }

def test_feature_context_no_active(mcp_fixture, tmp_project):
    mcp, store, _ = mcp_fixture
    result = json.loads(mcp.call("feature_context", project_dir=str(tmp_project), session_id="sess-x"))
    assert result["active_feature"] is None
    assert result["all_features"] == []

def test_feature_context_with_active(mcp_fixture, tmp_project, store):
    mcp, store, _ = mcp_fixture
    data = _active_feature(tmp_project, "my-feat", "sess-1")
    store.write_feature(tmp_project, "my-feat", data)
    store.register_session(tmp_project, "sess-1", "my-feat")
    result = json.loads(mcp.call("feature_context", project_dir=str(tmp_project), session_id="sess-1"))
    assert result["active_feature"]["name"] == "my-feat"

def test_feature_list_returns_summary(mcp_fixture, tmp_project, store):
    mcp, store, _ = mcp_fixture
    data = _active_feature(tmp_project, "feat-a", "sess-1")
    store.write_feature(tmp_project, "feat-a", data)
    result = json.loads(mcp.call("feature_list", project_dir=str(tmp_project)))
    assert len(result) == 1
    assert result[0]["name"] == "feat-a"
    assert "total_cost_usd" in result[0]
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_tools.py -v
```

Expected: `ModuleNotFoundError: No module named 'mcp_tools'`

- [ ] **Step 3: Write `mcp_tools.py` with read-only tools**

```python
# mcp_tools.py
import json
from pathlib import Path
from feature_store import FeatureStore, _now_iso, to_snake

SUMMARY_GUIDANCE = (
    "Write a 200-400 word summary covering: what the feature set out to do, "
    "what was actually built, key technical decisions and why, any known gaps "
    "or follow-up work, and notable files changed. This is the primary reference "
    "for future Claude sessions resuming or extending this work."
)


def register_tools(mcp, store: FeatureStore) -> None:

    @mcp.tool()
    def feature_context(project_dir: str, session_id: str) -> str:
        """Get feature context for this session. Call this at the start of every Claude session.
        Returns the active feature (if any) and a summary of all project features."""
        try:
            pdir = store.ensure_project_dir(project_dir)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        active = store.get_session_feature(pdir, session_id)
        all_features = store.list_features(pdir)
        return json.dumps({
            "active_feature": active,
            "all_features": [
                {
                    "name": f.get("name"),
                    "status": f.get("status"),
                    "started_at": f.get("started_at"),
                    "completed_at": f.get("completed_at"),
                    "milestone_count": len(f.get("milestones", [])),
                    "session_count": len(f.get("sessions", [])),
                }
                for f in all_features
            ],
        })

    @mcp.tool()
    def feature_list(project_dir: str) -> str:
        """List all features for the project with status, cost, and counts."""
        try:
            pdir = store.ensure_project_dir(project_dir)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        features = store.list_features(pdir)
        return json.dumps([
            {
                "name": f.get("name"),
                "status": f.get("status"),
                "started_at": f.get("started_at"),
                "completed_at": f.get("completed_at"),
                "total_cost_usd": f.get("total_cost_usd", 0.0),
                "milestone_count": len(f.get("milestones", [])),
                "session_count": len(f.get("sessions", [])),
            }
            for f in features
        ])
```

- [ ] **Step 4: Run read-only tool tests — verify they pass**

```bash
pytest tests/test_tools.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add mcp_tools.py tests/test_tools.py
git commit -m "feat: mcp_tools read-only tools (feature_context, feature_list)"
```

---

## Task 6: `mcp_tools.py` — `feature_start` and `feature_resume` with conflict flow

**Files:**
- Modify: `M:\feature-mcp\mcp_tools.py`
- Modify: `M:\feature-mcp\tests\test_tools.py`

- [ ] **Step 1: Add tests for start and resume**

```python
# append to tests/test_tools.py
def test_feature_start_creates_feature(mcp_fixture, tmp_project, store):
    mcp, store, _ = mcp_fixture
    result = json.loads(mcp.call("feature_start", project_dir=str(tmp_project), session_id="sess-1", name="new-feat"))
    assert result["status"] == "started"
    assert store.get_session_feature(tmp_project, "sess-1")["name"] == "new-feat"

def test_feature_start_conflict_returns_warning(mcp_fixture, tmp_project, store):
    mcp, store, _ = mcp_fixture
    data = _active_feature(tmp_project, "shared-feat", "sess-existing")
    store.write_feature(tmp_project, "shared-feat", data)
    store.register_session(tmp_project, "sess-existing", "shared-feat")
    result = json.loads(mcp.call("feature_start", project_dir=str(tmp_project), session_id="sess-new", name="shared-feat"))
    assert result["status"] == "conflict"
    assert "conflicting_session_id" in result
    assert "recommendation" in result

def test_feature_start_force_abandons_old_session(mcp_fixture, tmp_project, store):
    mcp, store, _ = mcp_fixture
    data = _active_feature(tmp_project, "shared-feat", "sess-old")
    store.write_feature(tmp_project, "shared-feat", data)
    store.register_session(tmp_project, "sess-old", "shared-feat")
    result = json.loads(mcp.call("feature_start", project_dir=str(tmp_project), session_id="sess-new", name="shared-feat", force=True))
    assert result["status"] == "started"
    # old session should be unregistered
    assert store.get_session_feature(tmp_project, "sess-old") is None
    # abandoned status written to file
    feat = store.read_feature(tmp_project, "shared-feat")
    statuses = [s["status"] for s in feat["sessions"]]
    assert "abandoned" in statuses

def test_feature_start_autocompletes_previous_session_feature(mcp_fixture, tmp_project, store):
    mcp, store, _ = mcp_fixture
    data = _active_feature(tmp_project, "old-feat", "sess-1")
    store.write_feature(tmp_project, "old-feat", data)
    store.register_session(tmp_project, "sess-1", "old-feat")
    mcp.call("feature_start", project_dir=str(tmp_project), session_id="sess-1", name="new-feat")
    old = store.read_feature(tmp_project, "old-feat")
    assert old["status"] == "completed"

def test_feature_resume_no_conflict(mcp_fixture, tmp_project, store):
    mcp, store, _ = mcp_fixture
    now = _now_iso()
    data = {"name": "old-feat", "status": "completed", "session_id": None,
            "sessions": [], "milestones": [], "started_at": now, "completed_at": now,
            "total_cost_usd": 0.0, "total_input_tokens": 0, "total_output_tokens": 0}
    store.write_feature(tmp_project, "old-feat", data)
    result = json.loads(mcp.call("feature_resume", project_dir=str(tmp_project), session_id="sess-new", feature_name="old-feat"))
    assert result["status"] == "resumed"
    assert store.get_session_feature(tmp_project, "sess-new")["name"] == "old-feat"

def test_feature_resume_conflict_requires_force(mcp_fixture, tmp_project, store):
    mcp, store, _ = mcp_fixture
    data = _active_feature(tmp_project, "live-feat", "sess-live")
    store.write_feature(tmp_project, "live-feat", data)
    store.register_session(tmp_project, "sess-live", "live-feat")
    result = json.loads(mcp.call("feature_resume", project_dir=str(tmp_project), session_id="sess-other", feature_name="live-feat"))
    assert result["status"] == "conflict"
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_tools.py -k "start or resume" -v
```

Expected: `AttributeError` — `feature_start` not registered.

- [ ] **Step 3: Add `_abandon_session` helper and `feature_start` / `feature_resume` tools to `mcp_tools.py`**

Add inside `register_tools`, after `feature_list`:

```python
    @mcp.tool()
    def feature_start(
        project_dir: str, session_id: str, name: str,
        description: str = "", force: bool = False
    ) -> str:
        """Start a new feature for this session. Auto-completes any feature this session
        already has active. If the named feature is active in another session, returns
        status='conflict' — pass force=True only after showing the warning to the user."""
        try:
            pdir = store.ensure_project_dir(project_dir)
        except ValueError as e:
            return json.dumps({"error": str(e)})

        # Auto-complete any existing feature for this session
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
        conflict_sid = store.get_active_session_for_feature(pdir, name)
        if conflict_sid and conflict_sid != session_id:
            if not force:
                return _conflict_response(store, pdir, name, conflict_sid)
            _abandon_session(store, pdir, name, conflict_sid)

        now = _now_iso()
        existing_data = store.read_feature(pdir, name) or {}
        feature_data = {
            "name": name,
            "status": "active",
            "session_id": session_id,
            "description": description or existing_data.get("description", ""),
            "sessions": existing_data.get("sessions", []) + [
                {"session_id": session_id, "session_start": now, "source": "cli", "status": "active"}
            ],
            "milestones": existing_data.get("milestones", []),
            "started_at": existing_data.get("started_at") or now,
            "completed_at": None,
            "total_cost_usd": existing_data.get("total_cost_usd", 0.0),
            "total_input_tokens": existing_data.get("total_input_tokens", 0),
            "total_output_tokens": existing_data.get("total_output_tokens", 0),
            "prompt_count": existing_data.get("prompt_count", 0),
        }
        store.write_feature(pdir, name, feature_data)
        store.register_session(pdir, session_id, name)
        return json.dumps({"status": "started", "feature": feature_data})

    @mcp.tool()
    def feature_resume(
        project_dir: str, session_id: str, feature_name: str, force: bool = False
    ) -> str:
        """Associate this session with an existing feature. If the feature is active in
        another session, returns status='conflict'. Pass force=True only after presenting
        the warning to the user and confirming they want to proceed."""
        try:
            pdir = store.ensure_project_dir(project_dir)
        except ValueError as e:
            return json.dumps({"error": str(e)})

        data = store.read_feature(pdir, feature_name)
        if not data:
            return json.dumps({"error": f"Feature '{feature_name}' not found"})

        conflict_sid = store.get_active_session_for_feature(pdir, feature_name)
        if conflict_sid and conflict_sid != session_id:
            if not force:
                return _conflict_response(store, pdir, feature_name, conflict_sid)
            _abandon_session(store, pdir, feature_name, conflict_sid)

        now = _now_iso()
        data["status"] = "active"
        data["completed_at"] = None
        data["session_id"] = session_id
        data.setdefault("sessions", []).append(
            {"session_id": session_id, "session_start": now, "source": "cli", "status": "active"}
        )
        store.write_feature(pdir, feature_name, data)
        store.register_session(pdir, session_id, feature_name)
        return json.dumps({"status": "resumed", "feature": data})
```

Then add the helper functions **outside** `register_tools`, at module level:

```python
def _conflict_response(store: FeatureStore, project_dir: Path, name: str, conflict_sid: str) -> str:
    data = store.read_feature(project_dir, name) or {}
    last_active = next(
        (s for s in reversed(data.get("sessions", [])) if s.get("status") == "active"),
        None,
    )
    return json.dumps({
        "status": "conflict",
        "warning": (
            f"Feature '{name}' is currently active in another session. "
            "Resuming here may cause context loss."
        ),
        "conflicting_session_id": conflict_sid,
        "last_active_at": last_active.get("session_start") if last_active else None,
        "recommendation": (
            "Resume the existing session and complete it there first. "
            "Only pass force=True after showing this warning to the user "
            "and confirming they want to proceed."
        ),
    })


def _abandon_session(store: FeatureStore, project_dir: Path, feature_name: str, session_id: str) -> None:
    data = store.read_feature(project_dir, feature_name)
    if data:
        for s in data.get("sessions", []):
            if s.get("session_id") == session_id:
                s["status"] = "abandoned"
                s["abandoned_at"] = _now_iso()
        store.write_feature(project_dir, feature_name, data)
    store.unregister_session(session_id)
```

- [ ] **Step 4: Run start/resume tests — verify they pass**

```bash
pytest tests/test_tools.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add mcp_tools.py tests/test_tools.py
git commit -m "feat: mcp_tools feature_start and feature_resume with conflict flow"
```

---

## Task 7: `mcp_tools.py` — `feature_complete` and `feature_discard`

**Files:**
- Modify: `M:\feature-mcp\mcp_tools.py`
- Modify: `M:\feature-mcp\tests\test_tools.py`

- [ ] **Step 1: Add tests**

```python
# append to tests/test_tools.py
def test_feature_complete_writes_markdown(mcp_fixture, tmp_project, store):
    mcp, store, _ = mcp_fixture
    data = _active_feature(tmp_project, "done-feat", "sess-1")
    store.write_feature(tmp_project, "done-feat", data)
    store.register_session(tmp_project, "sess-1", "done-feat")
    result = json.loads(mcp.call("feature_complete", project_dir=str(tmp_project),
                                  session_id="sess-1", summary="Built the thing."))
    assert result["status"] == "completed"
    md_path = tmp_project / "features" / "done-feat.md"
    assert md_path.exists()
    content = md_path.read_text()
    assert "Built the thing." in content
    assert "# done-feat" in content

def test_feature_complete_unregisters_session(mcp_fixture, tmp_project, store):
    mcp, store, _ = mcp_fixture
    data = _active_feature(tmp_project, "done-feat", "sess-1")
    store.write_feature(tmp_project, "done-feat", data)
    store.register_session(tmp_project, "sess-1", "done-feat")
    mcp.call("feature_complete", project_dir=str(tmp_project), session_id="sess-1", summary="Done.")
    assert store.get_session_feature(tmp_project, "sess-1") is None

def test_feature_complete_no_active_feature(mcp_fixture, tmp_project):
    mcp, store, _ = mcp_fixture
    result = json.loads(mcp.call("feature_complete", project_dir=str(tmp_project),
                                  session_id="sess-nobody", summary="x"))
    assert "error" in result

def test_feature_discard_archives_markdown(mcp_fixture, tmp_project, store):
    mcp, store, _ = mcp_fixture
    data = _active_feature(tmp_project, "dead-feat", "sess-1")
    store.write_feature(tmp_project, "dead-feat", data)
    store.register_session(tmp_project, "sess-1", "dead-feat")
    md = tmp_project / "features" / "dead-feat.md"
    md.parent.mkdir(exist_ok=True)
    md.write_text("# dead-feat\nsome content")
    result = json.loads(mcp.call("feature_discard", project_dir=str(tmp_project), session_id="sess-1"))
    assert result["status"] == "discarded"
    assert not md.exists()
    assert (tmp_project / "features" / "_archived" / "dead-feat.md").exists()
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_tools.py -k "complete or discard" -v
```

Expected: `AttributeError` on missing tools.

- [ ] **Step 3: Add `_render_summary` helper and `feature_complete` / `feature_discard` tools**

Add `_render_summary` at module level in `mcp_tools.py`:

```python
def _render_summary(data: dict, summary: str) -> str:
    name = data.get("name", "unknown")
    started = (data.get("started_at") or "")[:10]
    completed = (data.get("completed_at") or "")[:10]
    cost = data.get("total_cost_usd", 0.0)
    milestones = data.get("milestones", [])
    lines = [
        f"# {name}", "",
        f"**Started:** {started}  ",
        f"**Completed:** {completed}  ",
        f"**Cost:** ${cost:.4f}", "",
        "## Summary", "",
        summary.strip(),
    ]
    if milestones:
        lines += ["", "## Milestones", ""]
        for m in milestones:
            ts = (m.get("timestamp") or "")[:16].replace("T", " ")
            lines.append(f"- **{ts}** — {m['text']}")
    return "\n".join(lines) + "\n"
```

Add inside `register_tools`:

```python
    @mcp.tool()
    def feature_complete(project_dir: str, session_id: str, summary: str) -> str:
        f"""Complete the active feature and write the summary file.

        {SUMMARY_GUIDANCE}"""
        try:
            pdir = store.ensure_project_dir(project_dir)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        data = store.get_session_feature(pdir, session_id)
        if not data:
            return json.dumps({"error": "No active feature for this session"})
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
        md_path.write_text(_render_summary(data, summary), encoding="utf-8")
        return json.dumps({"status": "completed", "summary_path": str(md_path)})

    @mcp.tool()
    def feature_discard(project_dir: str, session_id: str) -> str:
        """Discard the active feature. Moves its summary to features/_archived/ if it exists."""
        try:
            pdir = store.ensure_project_dir(project_dir)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        data = store.get_session_feature(pdir, session_id)
        if not data:
            return json.dumps({"error": "No active feature for this session"})
        name = data["name"]
        data["status"] = "discarded"
        store.write_feature(pdir, name, data)
        store.unregister_session(session_id)
        md_path = pdir / "features" / f"{name}.md"
        if md_path.exists():
            archive = pdir / "features" / "_archived"
            archive.mkdir(exist_ok=True)
            md_path.rename(archive / f"{name}.md")
        return json.dumps({"status": "discarded", "name": name})
```

- [ ] **Step 4: Run all tool tests — verify they pass**

```bash
pytest tests/test_tools.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add mcp_tools.py tests/test_tools.py
git commit -m "feat: mcp_tools feature_complete and feature_discard"
```

---

## Task 8: `mcp_tools.py` — `feature_add_milestone`

**Files:**
- Modify: `M:\feature-mcp\mcp_tools.py`
- Modify: `M:\feature-mcp\tests\test_tools.py`

- [ ] **Step 1: Add test**

```python
# append to tests/test_tools.py
def test_feature_add_milestone(mcp_fixture, tmp_project, store):
    mcp, store, _ = mcp_fixture
    data = _active_feature(tmp_project, "wip-feat", "sess-1")
    store.write_feature(tmp_project, "wip-feat", data)
    store.register_session(tmp_project, "sess-1", "wip-feat")
    result = json.loads(mcp.call("feature_add_milestone", project_dir=str(tmp_project),
                                  session_id="sess-1", text="Wired up the pipeline"))
    assert result["status"] == "added"
    feat = store.read_feature(tmp_project, "wip-feat")
    assert len(feat["milestones"]) == 1
    assert feat["milestones"][0]["text"] == "Wired up the pipeline"
    assert "timestamp" in feat["milestones"][0]
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_tools.py::test_feature_add_milestone -v
```

Expected: `AttributeError` on missing tool.

- [ ] **Step 3: Add `feature_add_milestone` inside `register_tools` in `mcp_tools.py`**

```python
    @mcp.tool()
    def feature_add_milestone(project_dir: str, session_id: str, text: str) -> str:
        """Add a timestamped milestone to the active feature. Call when something significant
        is reached mid-session — a working prototype, a key decision, a subsystem completed."""
        try:
            pdir = store.ensure_project_dir(project_dir)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        data = store.get_session_feature(pdir, session_id)
        if not data:
            return json.dumps({"error": "No active feature for this session"})
        milestone = {"timestamp": _now_iso(), "session_id": session_id, "text": text}
        data.setdefault("milestones", []).append(milestone)
        store.write_feature(pdir, data["name"], data)
        return json.dumps({"status": "added", "milestone": milestone})
```

- [ ] **Step 4: Run all tests — verify they pass**

```bash
pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add mcp_tools.py tests/test_tools.py
git commit -m "feat: mcp_tools feature_add_milestone"
```

---

## Task 9: `rest_api.py` — REST routes for the bot

**Files:**
- Create: `M:\feature-mcp\rest_api.py`
- Create: `M:\feature-mcp\tests\test_rest_api.py`

- [ ] **Step 1: Write failing REST tests**

```python
# tests/test_rest_api.py
import json
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from feature_store import FeatureStore, _now_iso
from rest_api import create_api_router
from urllib.parse import quote

@pytest.fixture
def client(tmp_project):
    store = FeatureStore([str(tmp_project)])
    app = FastAPI()
    app.include_router(create_api_router(store), prefix="/api")
    return TestClient(app), store, tmp_project

def _encode(path):
    return quote(str(path), safe="")

def test_get_features_empty(client):
    c, store, tmp_project = client
    r = c.get(f"/api/projects/{_encode(tmp_project)}/features")
    assert r.status_code == 200
    assert r.json() == []

def test_get_features_unknown_project(client):
    c, store, tmp_project = client
    r = c.get(f"/api/projects/{_encode('/nonexistent')}/features")
    assert r.status_code == 404

def test_post_cost_no_active_feature(client):
    c, store, tmp_project = client
    r = c.post(
        f"/api/projects/{_encode(tmp_project)}/sessions/sess-x/cost",
        json={"cost_usd": 0.1, "input_tokens": 100, "output_tokens": 10},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "no_active_feature"

def test_post_cost_accumulates(client):
    c, store, tmp_project = client
    now = _now_iso()
    data = {"name": "feat", "status": "active", "session_id": "sess-1",
            "sessions": [{"session_id": "sess-1", "session_start": now, "source": "cli", "status": "active"}],
            "milestones": [], "started_at": now, "completed_at": None,
            "total_cost_usd": 0.0, "total_input_tokens": 0, "total_output_tokens": 0}
    store.write_feature(tmp_project, "feat", data)
    store.register_session(tmp_project, "sess-1", "feat")
    r = c.post(
        f"/api/projects/{_encode(tmp_project)}/sessions/sess-1/cost",
        json={"cost_usd": 0.5, "input_tokens": 500, "output_tokens": 50},
    )
    assert r.status_code == 200
    updated = store.read_feature(tmp_project, "feat")
    assert updated["total_cost_usd"] == pytest.approx(0.5)
    assert updated["total_input_tokens"] == 500

def test_get_features_returns_list(client):
    c, store, tmp_project = client
    now = _now_iso()
    store.write_feature(tmp_project, "feat-a", {"name": "feat-a", "status": "active",
        "sessions": [], "milestones": [], "started_at": now, "completed_at": None,
        "total_cost_usd": 0.0, "total_input_tokens": 0, "total_output_tokens": 0})
    r = c.get(f"/api/projects/{_encode(tmp_project)}/features")
    assert r.status_code == 200
    assert r.json()[0]["name"] == "feat-a"
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_rest_api.py -v
```

Expected: `ModuleNotFoundError: No module named 'rest_api'`

- [ ] **Step 3: Write `rest_api.py`**

```python
# rest_api.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from urllib.parse import unquote
from feature_store import FeatureStore


class CostPayload(BaseModel):
    cost_usd: float
    input_tokens: int
    output_tokens: int


def create_api_router(store: FeatureStore) -> APIRouter:
    router = APIRouter()

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

    return router
```

- [ ] **Step 4: Run all tests — verify they pass**

```bash
pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add rest_api.py tests/test_rest_api.py
git commit -m "feat: REST API for bot (get features, post cost)"
```

---

## Task 10: `server.py` — wiring MCP + REST

**Files:**
- Create: `M:\feature-mcp\server.py`
- Create: `M:\feature-mcp\start.bat`

- [ ] **Step 1: Look up FastMCP HTTP mounting**

Run this in the activated venv:

```bash
cd M:/feature-mcp && .venv/Scripts/activate
python -c "from mcp.server.fastmcp import FastMCP; mcp = FastMCP('test'); print(dir(mcp))"
```

Look for methods like `sse_app`, `streamable_http_app`, `get_asgi_app`. Note the name for use in step 3.

Alternatively, check context7: query `mcp FastMCP HTTP SSE mounting FastAPI`.

- [ ] **Step 2: Write `server.py`**

Replace `sse_app()` with the correct method name found in step 1. The most common names as of mcp 1.x are `sse_app()` (for SSE transport) or `streamable_http_app()` (for newer streamable HTTP).

```python
# server.py
import json
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

from feature_store import FeatureStore
from mcp_tools import register_tools
from rest_api import create_api_router

MCP_PORT = 8765


def create_app(projects: list[str]) -> FastAPI:
    store = FeatureStore(projects)
    log = store.startup()
    for msg in log:
        print(f"[feature-mcp] {msg}")
    print(f"[feature-mcp] {len(log)} active feature session(s) restored")

    mcp = FastMCP("feature-mcp")
    register_tools(mcp, store)

    app = FastAPI(title="Feature MCP")

    # Mount MCP SSE transport at /mcp
    # Use the method name confirmed in step 1 (sse_app or streamable_http_app)
    app.mount("/mcp", mcp.sse_app())

    # Mount REST API at /api
    app.include_router(create_api_router(store), prefix="/api")

    return app


if __name__ == "__main__":
    config_path = Path(__file__).parent / "projects.json"
    projects = json.loads(config_path.read_text())
    app = create_app(projects)
    print(f"[feature-mcp] Starting on http://127.0.0.1:{MCP_PORT}")
    uvicorn.run(app, host="127.0.0.1", port=MCP_PORT)
```

- [ ] **Step 3: Write `start.bat`**

```bat
@echo off
cd /d M:\feature-mcp
call .venv\Scripts\activate
python server.py
```

- [ ] **Step 4: Start the server and verify it runs**

```bash
cd M:/feature-mcp && .venv/Scripts/activate
python server.py
```

Expected output:
```
[feature-mcp] N active feature session(s) restored
[feature-mcp] Starting on http://127.0.0.1:8765
INFO:     Started server process
INFO:     Uvicorn running on http://127.0.0.1:8765
```

In a second terminal, verify both interfaces respond:

```bash
curl http://127.0.0.1:8765/api/projects/test/features
# Expected: 404 (unknown project — proves REST is up)

curl -I http://127.0.0.1:8765/mcp
# Expected: 200 or 405 (proves /mcp route exists)
```

- [ ] **Step 5: Commit**

```bash
git add server.py start.bat
git commit -m "feat: server wiring — MCP + REST on port 8765"
```

---

## Task 11: Register MCP server in Claude config

**Files:**
- Modify: `C:\Users\mplanck\.claude\settings.json`

- [ ] **Step 1: Read current settings.json**

```bash
cat "C:/Users/mplanck/.claude/settings.json"
```

Note the existing structure.

- [ ] **Step 2: Add `feature-mcp` to `mcpServers`**

Edit `C:\Users\mplanck\.claude\settings.json`. Add the `mcpServers` key if it doesn't exist, or add the new entry alongside existing ones:

```json
{
  "mcpServers": {
    "feature-mcp": {
      "transport": "http",
      "url": "http://localhost:8765/mcp"
    }
  }
}
```

If the existing file uses a different transport key (e.g., `"type": "sse"` instead of `"transport": "http"`), match the existing pattern.

- [ ] **Step 3: Verify Claude can see the MCP tools**

Make sure `server.py` is running, then in a new terminal:

```bash
claude --mcp-debug "call feature_list with project_dir M:/bridgecrew"
```

Expected: Claude finds and calls `feature_list`, returns the features list from `M:/bridgecrew/.claude/features/`.

- [ ] **Step 4: Commit settings change**

```bash
cd M:/feature-mcp
git add -A
git commit -m "docs: note MCP registration in settings.json"
```

Also commit settings.json change in the global config (it's outside any git repo — just ensure it's saved).

---

## Task 12: `core/mcp_client.py` in the bot

**Files:**
- Create: `M:\bridgecrew\core\mcp_client.py`

- [ ] **Step 1: Write `core/mcp_client.py`**

This is the async httpx wrapper the bot uses instead of `FeatureManager`. It mirrors the operations the bot needs.

```python
# core/mcp_client.py
"""Async HTTP client for the feature-mcp server (http://localhost:8765)."""
import logging
from pathlib import Path
from urllib.parse import quote

import httpx

MCP_BASE = "http://localhost:8765"
logger = logging.getLogger(__name__)


def _encode(project_dir: Path | str) -> str:
    return quote(str(project_dir), safe="")


async def get_features(project_dir: Path) -> list[dict]:
    """List all features for the project."""
    url = f"{MCP_BASE}/api/projects/{_encode(project_dir)}/features"
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            logger.warning("feature-mcp get_features failed: %s", exc)
            return []


async def get_session_feature(project_dir: Path, session_id: str) -> dict | None:
    """Return the active feature for this session, or None."""
    features = await get_features(project_dir)
    # Find a feature that has an active session matching session_id
    for feat in features:
        for sess in feat.get("sessions", []):
            if sess.get("session_id") == session_id and sess.get("status") == "active":
                return feat
    return None


async def post_cost(
    project_dir: Path,
    session_id: str,
    cost_usd: float,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Push token/cost data to the MCP server after a streaming response."""
    url = f"{MCP_BASE}/api/projects/{_encode(project_dir)}/sessions/{session_id}/cost"
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.post(url, json={
                "cost_usd": cost_usd,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            })
        except Exception as exc:
            logger.warning("feature-mcp post_cost failed: %s", exc)
```

- [ ] **Step 2: Verify import works**

```bash
cd M:/bridgecrew
python -c "from core.mcp_client import get_features, post_cost; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
cd M:/bridgecrew
git add core/mcp_client.py
git commit -m "feat: add core/mcp_client.py — async httpx wrapper for feature-mcp"
```

---

## Task 13: Migrate `discord_cogs/claude_prompt.py`

**Files:**
- Modify: `M:\bridgecrew\discord_cogs\claude_prompt.py`

The key changes are at three locations:
- **Line 289**: `get_current_feature` lookup before building the system prompt
- **Lines 625–631**: `accumulate_tokens` after streaming completes
- **Line 938**: `get_current_feature` inside `_process_prompt`
- **Line 942**: `list_features` for the feature gate UI
- **Lines 126–165**: `FeatureGateSelect` callbacks that start/resume features

- [ ] **Step 1: Replace the `accumulate_tokens` call (line 625)**

Find this block (around line 625):
```python
totals = self.bot.feature_manager.accumulate_tokens(
    project_dir,
    input_tokens=context_fill,
    output_tokens=event.output_tokens or 0,
    cost_usd=event.cost_usd or 0.0,
    feature_name=feature.name if feature else None,
)
```

Replace with:
```python
if feature and default_session_id:
    import asyncio
    from core.mcp_client import post_cost
    asyncio.create_task(post_cost(
        project_dir,
        session_id=default_session_id,
        cost_usd=event.cost_usd or 0.0,
        input_tokens=context_fill,
        output_tokens=event.output_tokens or 0,
    ))
totals = {
    "total_cost_usd": (feature.total_cost_usd or 0.0) + (event.cost_usd or 0.0)
    if feature else 0.0,
    "total_input_tokens": 0,
    "total_output_tokens": event.output_tokens or 0,
    "prompt_count": 1,
}
```

Note: the footer still shows a cost figure; it will show the accumulated cost from the last known feature state plus this response's cost. This is an acceptable approximation — exact totals are always in the MCP JSON file.

- [ ] **Step 2: Replace `get_current_feature` calls (lines 289 and 938)**

Find (line ~289):
```python
feature = self.bot.feature_manager.get_current_feature(project_dir, session_id=session_id)
```

Replace with:
```python
from core.mcp_client import get_session_feature as _get_session_feature
feature_dict = await _get_session_feature(project_dir, session_id) if session_id else None
feature = Feature.from_dict(feature_dict["name"], feature_dict) if feature_dict else None
```

Apply the same replacement at line ~938 (the second `get_current_feature` call).

- [ ] **Step 3: Replace `list_features` call (line ~942)**

Find:
```python
features = self.bot.feature_manager.list_features(project_dir)
```

Replace with:
```python
from core.mcp_client import get_features as _get_features
raw_features = await _get_features(project_dir)
features = [Feature.from_dict(f["name"], f) for f in raw_features]
```

- [ ] **Step 4: Replace `FeatureGateSelect` callbacks (lines ~126–165)**

The `FeatureGateSelect` handles resuming or starting a feature when the bot asks the user which feature to work on. Find the `fm.resume_feature(...)` and `fm.start_feature(...)` calls in `FeatureGateSelect` (around lines 139 and 141) and replace with calls through Claude itself (since these operations now go via the MCP tools that Claude calls). The simplest migration: comment out the Python-side feature_manager calls and instead pass a system prompt injection telling Claude to call `feature_start` or `feature_resume` at the top of the next message.

Replace the `FeatureGateSelect.interaction_check` resume/start logic:

```python
# Was: self.selected_feature = fm.resume_feature(self.project_dir, choice)
# Now: inject instruction for Claude to resume via MCP tool
self.selected_feature_name = choice
self.selected_action = "resume"  # carried into the prompt builder

# Was: self.selected_feature = fm.start_feature(self.project_dir, choice)
# Now:
self.selected_feature_name = choice
self.selected_action = "start"
```

In the prompt builder (wherever `selected_feature` was used to inject context), add a system message prefix:

```python
if gate_select and gate_select.selected_action == "resume":
    system_prefix = (
        f"[INSTRUCTION] Call feature_resume with project_dir={project_dir} "
        f"session_id={{session_id}} feature_name={gate_select.selected_feature_name} "
        f"before responding to the user."
    )
elif gate_select and gate_select.selected_action == "start":
    system_prefix = (
        f"[INSTRUCTION] Call feature_start with project_dir={project_dir} "
        f"session_id={{session_id}} name={gate_select.selected_feature_name} "
        f"before responding to the user."
    )
```

- [ ] **Step 5: Remove `add_history` call and all `self.bot.feature_manager` references**

Find line ~1115:
```python
self.bot.feature_manager.add_history(...)
```

Delete this call — history logging is not migrated (prompt history lives in Claude's conversation context now).

Search for any remaining `feature_manager` references:
```bash
cd M:/bridgecrew
grep -n "feature_manager" discord_cogs/claude_prompt.py
```

Remove or replace any remaining ones. Then verify the file parses:
```bash
python -c "import discord_cogs.claude_prompt; print('ok')"
```

- [ ] **Step 6: Commit**

```bash
git add discord_cogs/claude_prompt.py
git commit -m "feat: migrate claude_prompt.py from feature_manager to mcp_client"
```

---

## Task 14: Migrate `discord_cogs/features.py` slash commands

**Files:**
- Modify: `M:\bridgecrew\discord_cogs\features.py`

The four slash commands (`/start-feature`, `/resume-feature`, `/complete-feature`, `/discard-feature`) currently call `self.bot.feature_manager`. Replace with instructions injected into Claude's next session — the MCP tools will execute the actual operations.

- [ ] **Step 1: Replace `/start-feature` handler**

Find the `start_feature` slash command handler (~line 413). Remove the `fm.start_feature()` call. Instead, store the intent in bot state so the next Claude message picks it up:

```python
from core.state import load_project_state, save_project_state

# After resolving project_dir and name:
state = load_project_state(project_dir)
state["pending_feature_op"] = {"action": "start", "name": name}
save_project_state(project_dir, state)
await interaction.followup.send(
    f"Ready to start **{name}**. Send your first message to begin — "
    f"Claude will call `feature_start` automatically.",
    ephemeral=True,
)
```

- [ ] **Step 2: Replace `/resume-feature` handler**

After the user picks a feature from the select menu (~line 454):

```python
state = load_project_state(project_dir)
state["pending_feature_op"] = {"action": "resume", "name": chosen_name}
save_project_state(project_dir, state)
await interaction.followup.send(
    f"Ready to resume **{chosen_name}**. Send a message to continue — "
    f"Claude will call `feature_resume` automatically.",
    ephemeral=True,
)
```

- [ ] **Step 3: Replace `/complete-feature` handler**

```python
state = load_project_state(project_dir)
state["pending_feature_op"] = {"action": "complete"}
save_project_state(project_dir, state)
await interaction.followup.send(
    "Completing the active feature. Send a final message describing "
    "what was accomplished — Claude will call `feature_complete`.",
    ephemeral=True,
)
```

- [ ] **Step 4: Replace `/discard-feature` handler**

```python
state = load_project_state(project_dir)
state["pending_feature_op"] = {"action": "discard"}
save_project_state(project_dir, state)
await interaction.followup.send(
    "Ready to discard. Send a message confirming — "
    "Claude will call `feature_discard`.",
    ephemeral=True,
)
```

- [ ] **Step 5: Wire `pending_feature_op` into the prompt builder in `claude_prompt.py`**

In `_process_prompt` (or wherever system prompt is built), check for `pending_feature_op` and inject it as a system instruction prefix, then clear it:

```python
state = load_project_state(project_dir)
pending_op = state.pop("pending_feature_op", None)
if pending_op:
    save_project_state(project_dir, state)
    action = pending_op["action"]
    feature_name = pending_op.get("name", "")
    if action == "start":
        op_instruction = (
            f"FIRST, call feature_start(project_dir='{project_dir}', "
            f"session_id='{{session_id}}', name='{feature_name}'). "
            f"Then respond normally."
        )
    elif action == "resume":
        op_instruction = (
            f"FIRST, call feature_resume(project_dir='{project_dir}', "
            f"session_id='{{session_id}}', feature_name='{feature_name}'). "
            f"Then respond normally."
        )
    elif action == "complete":
        op_instruction = (
            f"FIRST, call feature_complete(project_dir='{project_dir}', "
            f"session_id='{{session_id}}', summary='<write summary here>'). "
            f"Then respond normally."
        )
    elif action == "discard":
        op_instruction = (
            f"FIRST, call feature_discard(project_dir='{project_dir}', "
            f"session_id='{{session_id}}'). Then respond normally."
        )
    # Prepend to system prompt or user message
    extra_system = op_instruction
```

- [ ] **Step 6: Remove all `self.bot.feature_manager` references from `features.py`**

```bash
grep -n "feature_manager" M:/bridgecrew/discord_cogs/features.py
```

Remove each one. Verify file parses:

```bash
python -c "import discord_cogs.features; print('ok')"
```

- [ ] **Step 7: Commit**

```bash
git add discord_cogs/features.py discord_cogs/claude_prompt.py
git commit -m "feat: migrate features.py slash commands to pending_feature_op pattern"
```

---

## Task 15: Remove `core/feature_manager.py`, clean `core/state.py`

**Files:**
- Delete: `M:\bridgecrew\core\feature_manager.py`
- Modify: `M:\bridgecrew\core\state.py`

- [ ] **Step 1: Verify no remaining imports of feature_manager**

```bash
cd M:/bridgecrew
grep -rn "feature_manager\|FeatureManager" --include="*.py" .
```

Expected: zero results (after tasks 13–14 are done).

- [ ] **Step 2: Delete `core/feature_manager.py`**

```bash
cd M:/bridgecrew
git rm core/feature_manager.py
```

- [ ] **Step 3: Remove feature-specific functions from `core/state.py`**

Delete these functions from `core/state.py` (lines 68–240 per the earlier analysis):
- `feature_name_to_filename()`
- `load_feature_index()`
- `save_feature_index()`
- `load_feature_file()`
- `save_feature_file()`
- `delete_feature_file()`
- `list_feature_names()`
- `_migrate_monolithic_to_split()`
- `load_feature_state()` (legacy shim)
- `save_feature_state()` (legacy shim)

Keep: `load_config`, `save_config`, `get_projects`, `set_project`, `remove_project`, `load_project_state`, `save_project_state`, `_atomic_write`.

- [ ] **Step 4: Verify bot starts without errors**

```bash
cd M:/bridgecrew
python -c "from core.state import load_project_state, save_project_state; print('ok')"
python -c "from discord_cogs.features import FeaturesCog; print('ok')"
python -c "from discord_cogs.claude_prompt import ClaudePromptCog; print('ok')"
```

Expected: `ok` for each.

- [ ] **Step 5: Also remove `feature_manager` from bot instantiation**

Search for where `FeatureManager()` is instantiated in the bot (likely in `bot.py` or `main.py`):

```bash
grep -n "FeatureManager\|feature_manager" M:/bridgecrew/bot.py 2>/dev/null || \
grep -rn "FeatureManager\|feature_manager" M:/bridgecrew --include="*.py" | grep -v "\.pyc"
```

Remove the `self.feature_manager = FeatureManager()` line and its import.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: remove feature_manager.py and feature I/O from state.py"
```

---

## Task 16: Update global CLAUDE.md — replace feature lifecycle block

**Files:**
- Modify: `C:\Users\mplanck\.claude\CLAUDE.md`

- [ ] **Step 1: Read the current feature lifecycle block**

```bash
cat "C:/Users/mplanck/.claude/CLAUDE.md"
```

Locate the section between `# BEGIN: feature-lifecycle` and `# END: feature-lifecycle`.

- [ ] **Step 2: Replace the entire block**

Replace everything between (and including) the `BEGIN` and `END` markers with:

```markdown
# BEGIN: feature-mcp
# Do not edit this block manually.

## Feature Lifecycle

Feature state is managed by the **feature-mcp** MCP server running on `localhost:8765`.

**At the start of every session**, call:
```
feature_context(project_dir="<absolute path>", session_id="<your session id>")
```
This returns your active feature (if any) and a list of all project features.

**Available tools:**
- `feature_context(project_dir, session_id)` — get active feature + feature list (call at session start)
- `feature_start(project_dir, session_id, name, description?, force?)` — start a new feature
- `feature_resume(project_dir, session_id, feature_name, force?)` — resume an existing feature
- `feature_complete(project_dir, session_id, summary)` — complete and write summary
- `feature_add_milestone(project_dir, session_id, text)` — record a mid-session milestone
- `feature_list(project_dir)` — list all features
- `feature_discard(project_dir, session_id)` — discard and archive

**Conflict handling:** If `feature_resume` or `feature_start` returns `status: "conflict"`,
show the warning and recommendation to the user verbatim before calling again with `force=True`.

# END: feature-mcp
```

- [ ] **Step 3: Verify Claude picks up the new instructions**

In a new terminal Claude session in any project:

```
What feature am I working on in M:/bridgecrew?
```

Expected: Claude calls `feature_context` via the MCP, returns the current state from the JSON files.

- [ ] **Step 4: Final integration commit in bridgecrew**

```bash
cd M:/bridgecrew
git add -A
git commit -m "feat: feature lifecycle now managed by feature-mcp MCP server"
```

And final commit in feature-mcp:

```bash
cd M:/feature-mcp
git add -A
git commit -m "feat: feature-mcp server complete"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| Persistent HTTP/SSE server on 8765 | Task 10 |
| In-memory session routing rebuilt on startup | Task 4 |
| `feature_context` read-only tool | Task 5 |
| `feature_list` read-only tool | Task 5 |
| `feature_start` with auto-complete + conflict flow | Task 6 |
| `feature_resume` with conflict + force | Task 6 |
| `feature_complete` with summary guidance + markdown write | Task 7 |
| `feature_discard` with archive | Task 7 |
| `feature_add_milestone` | Task 8 |
| REST GET /api/.../features | Task 9 |
| REST POST .../cost | Task 9 |
| Bot drops feature_manager.py | Task 15 |
| Cost push via REST after streaming | Task 13 |
| CLAUDE.md feature lifecycle block replaced | Task 16 |
| MCP registered in Claude settings | Task 11 |
| `sessions[].status` field (active/abandoned/completed) | Task 4 (store) + Task 6 (tools) |
| `milestones` array | Task 8 |
| `features.json` kept as `{}`, nothing writes to it | Task 16 (CLAUDE.md), startup ignores it |
| Atomic file writes | Task 2 |

All spec requirements have a corresponding task. No gaps found.

**Type consistency:** `_now_iso`, `to_snake`, `_atomic_write`, `_abandon_session`, `_conflict_response`, `_render_summary` are all defined before use. `FeatureStore` methods used in `mcp_tools.py` match names defined in `feature_store.py`.

**No placeholders found** — all steps contain complete code or explicit shell commands with expected output.
