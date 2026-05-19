# Feature MCP Session Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix cross-session contamination in feature-mcp so a CLI session and a Discord bot session can each hold an active feature independently without either evicting the other.

**Architecture:** Two surgical changes — `startup()` stops restoring ephemeral CLI sessions into memory, and the `feature_context` fallback checks whether a candidate feature already has a live session before auto-associating. No data model or protocol changes.

**Tech Stack:** Python 3.11, pytest, FastAPI TestClient (tests only)

---

## File Map

| File | Change |
|---|---|
| `feature-mcp/feature_store.py` | Add `source != "cli"` guard in `startup()` |
| `feature-mcp/mcp_tools.py` | Replace blind fallback loop with orphan-detection logic |
| `feature-mcp/tests/test_feature_store.py` | Update broken startup test; add CLI-skip test |
| `feature-mcp/tests/test_e2e_lifecycle.py` | Add `TestMultiSessionIsolation` class |

---

## Task 1: Fix `startup()` — skip CLI sessions on recovery

**Files:**
- Modify: `feature-mcp/feature_store.py:113`
- Test: `feature-mcp/tests/test_feature_store.py`

- [ ] **Step 1: Update the existing startup test (it will break after the fix)**

The test `test_startup_rebuilds_routing` at line 82 writes a `source: "cli"` session and asserts it IS restored. After the fix it won't be. Replace it with two focused tests — one for REST (restored) and one for CLI (skipped).

In `feature-mcp/tests/test_feature_store.py`, replace lines 82–97 with:

```python
def test_startup_restores_rest_sessions(tmp_project):
    from feature_store import FeatureStore, _now_iso
    now = _now_iso()
    data = {
        "name": "feat-a", "status": "active", "session_id": "rest-sess",
        "sessions": [{"session_id": "rest-sess", "session_start": now,
                       "source": "rest", "status": "active"}],
        "milestones": [], "started_at": now, "completed_at": None,
        "total_cost_usd": 0.0, "total_input_tokens": 0, "total_output_tokens": 0,
    }
    store2 = FeatureStore([str(tmp_project)])
    store2.write_feature(tmp_project, "feat-a", data)
    log = store2.startup()
    assert store2.get_session_feature(tmp_project, "rest-sess") is not None
    assert any("feat-a" in msg for msg in log)


def test_startup_skips_cli_sessions(tmp_project):
    from feature_store import FeatureStore, _now_iso
    now = _now_iso()
    data = {
        "name": "feat-b", "status": "active", "session_id": "cli-sess",
        "sessions": [{"session_id": "cli-sess", "session_start": now,
                       "source": "cli", "status": "active"}],
        "milestones": [], "started_at": now, "completed_at": None,
        "total_cost_usd": 0.0, "total_input_tokens": 0, "total_output_tokens": 0,
    }
    store2 = FeatureStore([str(tmp_project)])
    store2.write_feature(tmp_project, "feat-b", data)
    store2.startup()
    assert store2.get_session_feature(tmp_project, "cli-sess") is None
```

- [ ] **Step 2: Run the new tests to confirm they fail**

```
cd feature-mcp && .venv\Scripts\pytest tests/test_feature_store.py::test_startup_restores_rest_sessions tests/test_feature_store.py::test_startup_skips_cli_sessions -v
```

Expected: `test_startup_restores_rest_sessions` FAILS (source filter not yet in code), `test_startup_skips_cli_sessions` FAILS (CLI sessions still restored).

- [ ] **Step 3: Apply the fix in `feature_store.py`**

In `feature-mcp/feature_store.py`, change lines 112–118 from:

```python
                for sess in data.get("sessions", []):
                    if sess.get("status") == "active":
                        self._sessions[sess["session_id"]] = (project_dir, feature_name)
                        log.append(
                            f"Restored: {project_dir.name}/{feature_name}"
                            f" <- {sess['session_id'][:8]}"
                        )
```

to:

```python
                for sess in data.get("sessions", []):
                    if sess.get("status") == "active" and sess.get("source") != "cli":
                        self._sessions[sess["session_id"]] = (project_dir, feature_name)
                        log.append(
                            f"Restored: {project_dir.name}/{feature_name}"
                            f" <- {sess['session_id'][:8]}"
                        )
```

- [ ] **Step 4: Run the targeted tests to confirm they pass**

```
cd feature-mcp && .venv\Scripts\pytest tests/test_feature_store.py::test_startup_restores_rest_sessions tests/test_feature_store.py::test_startup_skips_cli_sessions -v
```

Expected: both PASS.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

```
cd feature-mcp && .venv\Scripts\pytest -v
```

Expected: all tests pass. If `test_startup_rebuilds_routing` still exists, it will fail — it was replaced in Step 1.

- [ ] **Step 6: Commit**

```
git add feature-mcp/feature_store.py feature-mcp/tests/test_feature_store.py
git commit -m "fix: skip CLI sessions during startup recovery to prevent phantom session locks"
```

---

## Task 2: Fix `feature_context` fallback — session-aware orphan detection

**Files:**
- Modify: `feature-mcp/mcp_tools.py:29-41`
- Test: `feature-mcp/tests/test_e2e_lifecycle.py`

- [ ] **Step 1: Add the `TestMultiSessionIsolation` class with failing tests**

Append this class to `feature-mcp/tests/test_e2e_lifecycle.py`:

```python
# ── TestMultiSessionIsolation ─────────────────────────────────────────────

class TestMultiSessionIsolation:
    def test_context_fallback_ignores_live_rest_feature(self, e2e):
        """CLI session must not auto-associate with a feature owned by a live REST session."""
        mcp, store, client, proj = e2e
        store.register_session(proj, "rest-bot", "feature-x")
        store.write_feature(proj, "feature-x", {
            "name": "feature-x", "status": "active", "session_id": "rest-bot",
            "sessions": [{"session_id": "rest-bot", "session_start": _now_iso(),
                           "source": "rest", "status": "active"}],
            "milestones": [], "started_at": _now_iso(), "completed_at": None,
            "total_cost_usd": 0.0, "total_input_tokens": 0, "total_output_tokens": 0,
        })
        result = json.loads(mcp.call("feature_context",
                                     project_dir=str(proj), session_id="cli-new"))
        assert result["active_feature"] is None

    def test_context_fallback_auto_associates_single_orphan(self, e2e):
        """CLI session auto-associates with an active feature that has no live session."""
        mcp, store, client, proj = e2e
        store.write_feature(proj, "feature-y", {
            "name": "feature-y", "status": "active", "session_id": "stale-cli",
            "sessions": [{"session_id": "stale-cli", "session_start": _now_iso(),
                           "source": "cli", "status": "active"}],
            "milestones": [], "started_at": _now_iso(), "completed_at": None,
            "total_cost_usd": 0.0, "total_input_tokens": 0, "total_output_tokens": 0,
        })
        result = json.loads(mcp.call("feature_context",
                                     project_dir=str(proj), session_id="cli-new"))
        assert result["active_feature"] is not None
        assert result["active_feature"]["name"] == "feature-y"

    def test_context_fallback_returns_candidates_for_multiple_orphans(self, e2e):
        """When multiple orphaned features exist, return resume_candidates and no auto-associate."""
        mcp, store, client, proj = e2e
        for name in ["alpha-feat", "beta-feat"]:
            store.write_feature(proj, name, {
                "name": name, "status": "active", "session_id": "stale-cli",
                "sessions": [{"session_id": "stale-cli", "session_start": _now_iso(),
                               "source": "cli", "status": "active"}],
                "milestones": [], "started_at": _now_iso(), "completed_at": None,
                "total_cost_usd": 0.0, "total_input_tokens": 0, "total_output_tokens": 0,
            })
        result = json.loads(mcp.call("feature_context",
                                     project_dir=str(proj), session_id="cli-new"))
        assert result["active_feature"] is None
        assert set(result["resume_candidates"]) == {"alpha-feat", "beta-feat"}

    def test_new_cli_session_finds_own_orphaned_feature_not_bot_feature(self, e2e):
        """Core regression: bot's live feature (alphabetically first) must not be grabbed
        by a new CLI session when the CLI's own orphaned feature also exists."""
        mcp, store, client, proj = e2e
        # feature-x (bot, live in memory, source=rest) sorts before feature-y alphabetically
        store.register_session(proj, "rest-bot", "feature-x")
        store.write_feature(proj, "feature-x", {
            "name": "feature-x", "status": "active", "session_id": "rest-bot",
            "sessions": [{"session_id": "rest-bot", "session_start": _now_iso(),
                           "source": "rest", "status": "active"}],
            "milestones": [], "started_at": _now_iso(), "completed_at": None,
            "total_cost_usd": 0.0, "total_input_tokens": 0, "total_output_tokens": 0,
        })
        # feature-y (CLI, orphaned — no in-memory session)
        store.write_feature(proj, "feature-y", {
            "name": "feature-y", "status": "active", "session_id": "old-cli",
            "sessions": [{"session_id": "old-cli", "session_start": _now_iso(),
                           "source": "cli", "status": "active"}],
            "milestones": [], "started_at": _now_iso(), "completed_at": None,
            "total_cost_usd": 0.0, "total_input_tokens": 0, "total_output_tokens": 0,
        })
        result = json.loads(mcp.call("feature_context",
                                     project_dir=str(proj), session_id="cli-new"))
        assert result["active_feature"] is not None
        assert result["active_feature"]["name"] == "feature-y"
```

- [ ] **Step 2: Run the new tests to confirm they fail**

```
cd feature-mcp && .venv\Scripts\pytest tests/test_e2e_lifecycle.py::TestMultiSessionIsolation -v
```

Expected: all four tests FAIL (the current fallback always grabs the first active feature regardless of live sessions, and `resume_candidates` key doesn't exist yet).

- [ ] **Step 3: Replace the fallback block in `mcp_tools.py`**

In `feature-mcp/mcp_tools.py`, replace lines 29–41 (the `if active is None:` block) with:

```python
        resume_candidates: list[str] = []
        if active is None:
            orphaned = [
                f for f in store.list_features(pdir)
                if f.get("status") == "active"
                and store.get_active_session_for_feature(pdir, f["name"]) is None
            ]
            if len(orphaned) == 1:
                f = orphaned[0]
                now = _now_iso()
                f.setdefault("sessions", []).append(
                    {"session_id": session_id, "session_start": now,
                     "source": "cli", "status": "active"}
                )
                f["session_id"] = session_id
                store.write_feature(pdir, f["name"], f)
                store.register_session(pdir, session_id, f["name"])
                active = f
            elif len(orphaned) > 1:
                resume_candidates = [f["name"] for f in orphaned]
```

Also update the `return json.dumps(...)` call (currently at line 42) to include `resume_candidates`:

```python
        all_features = store.list_features(pdir)
        return json.dumps({
            "active_feature": active,
            "resume_candidates": resume_candidates,
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
```

- [ ] **Step 4: Run the new tests to confirm they pass**

```
cd feature-mcp && .venv\Scripts\pytest tests/test_e2e_lifecycle.py::TestMultiSessionIsolation -v
```

Expected: all four tests PASS.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

```
cd feature-mcp && .venv\Scripts\pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```
git add feature-mcp/mcp_tools.py feature-mcp/tests/test_e2e_lifecycle.py
git commit -m "fix: feature_context fallback only auto-associates with orphaned features, returns resume_candidates when ambiguous"
```
