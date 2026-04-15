# Abandon Feature Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `feature_abandon_sessions` MCP tool and `/abandon-feature-sessions` Discord slash command that clears stale session locks on a feature so it can be resumed without a conflict error.

**Architecture:** A shared `_abandon_all_sessions(store, project_dir, feature_name)` helper does all the work — it unregisters in-memory sessions, marks active session entries in the JSON as `abandoned`, and clears the top-level `session_id` field. Both the new MCP tool and new REST endpoint delegate to this helper. The Discord bot calls the REST endpoint via a new `mcp_client.abandon_feature_sessions()` function.

**Tech Stack:** Python 3.11, FastAPI, discord.py (app_commands), httpx, pytest

---

## File Map

```
feature-mcp/mcp_tools.py          Modify — add _abandon_all_sessions helper + feature_abandon_sessions tool
feature-mcp/rest_api.py           Modify — add POST .../features/{name}/abandon-sessions endpoint
feature-mcp/tests/test_tools.py   Modify — tests for feature_abandon_sessions
feature-mcp/tests/test_rest_api.py Modify — tests for abandon-sessions endpoint
core/mcp_client.py                Modify — add abandon_feature_sessions() async function
discord_cogs/features.py          Modify — add /abandon-feature-sessions command + UI classes
```

---

## Task 1: `_abandon_all_sessions` helper and `feature_abandon_sessions` MCP tool

**Files:**
- Modify: `feature-mcp/mcp_tools.py`
- Modify: `feature-mcp/tests/test_tools.py`

Working directory for all pytest commands: `feature-mcp/`

- [ ] **Step 1: Write failing tests**

Append to `feature-mcp/tests/test_tools.py`:

```python
# --- feature_abandon_sessions ---

def test_feature_abandon_sessions_clears_in_memory_session(mcp_fixture, tmp_project, store):
    mcp, store, _ = mcp_fixture
    data = _active_feature("locked-feat", "sess-stale")
    store.write_feature(tmp_project, "locked-feat", data)
    store.register_session(tmp_project, "sess-stale", "locked-feat")

    result = json.loads(mcp.call("feature_abandon_sessions",
                                  project_dir=str(tmp_project),
                                  feature_name="locked-feat"))

    assert result["status"] == "ok"
    assert result["abandoned_count"] >= 1
    # Session removed from in-memory registry
    assert store.get_session_feature(tmp_project, "sess-stale") is None
    # Session marked abandoned in JSON
    feat = store.read_feature(tmp_project, "locked-feat")
    statuses = [s["status"] for s in feat["sessions"]]
    assert "abandoned" in statuses
    assert "active" not in statuses


def test_feature_abandon_sessions_clears_stale_json_session(mcp_fixture, tmp_project, store):
    """Sessions in JSON but not in memory (e.g. after server restart) are also cleared."""
    mcp, store, _ = mcp_fixture
    from feature_store import _now_iso as _n
    now = _n()
    # Write a feature with an active session directly — don't register in memory
    data = {
        "name": "stale-feat", "status": "active", "session_id": "sess-ghost",
        "sessions": [{"session_id": "sess-ghost", "session_start": now,
                       "source": "cli", "status": "active"}],
        "milestones": [], "started_at": now, "completed_at": None,
        "total_cost_usd": 0.0, "total_input_tokens": 0, "total_output_tokens": 0,
    }
    store.write_feature(tmp_project, "stale-feat", data)
    # Intentionally NOT calling store.register_session

    result = json.loads(mcp.call("feature_abandon_sessions",
                                  project_dir=str(tmp_project),
                                  feature_name="stale-feat"))

    assert result["status"] == "ok"
    feat = store.read_feature(tmp_project, "stale-feat")
    statuses = [s["status"] for s in feat["sessions"]]
    assert "abandoned" in statuses
    assert "active" not in statuses


def test_feature_abandon_sessions_clears_session_id_field(mcp_fixture, tmp_project, store):
    mcp, store, _ = mcp_fixture
    data = _active_feature("ptr-feat", "sess-ptr")
    store.write_feature(tmp_project, "ptr-feat", data)
    store.register_session(tmp_project, "sess-ptr", "ptr-feat")

    mcp.call("feature_abandon_sessions",
             project_dir=str(tmp_project), feature_name="ptr-feat")

    feat = store.read_feature(tmp_project, "ptr-feat")
    assert feat["session_id"] is None


def test_feature_abandon_sessions_preserves_feature_status(mcp_fixture, tmp_project, store):
    """Feature status stays 'active' — the feature is still ongoing, just unlocked."""
    mcp, store, _ = mcp_fixture
    data = _active_feature("still-active", "sess-1")
    store.write_feature(tmp_project, "still-active", data)
    store.register_session(tmp_project, "sess-1", "still-active")

    mcp.call("feature_abandon_sessions",
             project_dir=str(tmp_project), feature_name="still-active")

    feat = store.read_feature(tmp_project, "still-active")
    assert feat["status"] == "active"


def test_feature_abandon_sessions_unknown_feature(mcp_fixture, tmp_project):
    mcp, store, _ = mcp_fixture
    result = json.loads(mcp.call("feature_abandon_sessions",
                                  project_dir=str(tmp_project),
                                  feature_name="does-not-exist"))
    assert "error" in result


def test_feature_abandon_sessions_allows_clean_resume_after(mcp_fixture, tmp_project, store):
    """After abandoning sessions, feature_resume succeeds without conflict."""
    mcp, store, _ = mcp_fixture
    data = _active_feature("resumable", "sess-old")
    store.write_feature(tmp_project, "resumable", data)
    store.register_session(tmp_project, "sess-old", "resumable")

    mcp.call("feature_abandon_sessions",
             project_dir=str(tmp_project), feature_name="resumable")

    result = json.loads(mcp.call("feature_resume",
                                  project_dir=str(tmp_project),
                                  session_id="sess-new", feature_name="resumable"))
    assert result["status"] == "resumed"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd feature-mcp && .venv/Scripts/python -m pytest tests/test_tools.py -k "abandon" -v
```

Expected: 6 failures with `KeyError` or similar (tool not registered yet).

- [ ] **Step 3: Add `_abandon_all_sessions` helper to `mcp_tools.py`**

In `feature-mcp/mcp_tools.py`, add this function after the existing `_abandon_session` helper (around line 269):

```python
def _abandon_all_sessions(store: FeatureStore, project_dir: Path, feature_name: str) -> int:
    """Abandon all active sessions for a feature (both in-memory and stale JSON entries).
    Clears the top-level session_id pointer. Returns the number of session entries abandoned."""
    now = _now_iso()

    # Collect all session IDs registered in memory for this feature
    active_sids = [
        sid for sid, (pdir, fname) in list(store._sessions.items())
        if pdir == project_dir and to_snake(fname) == to_snake(feature_name)
    ]

    # Read feature data once
    data = store.read_feature(project_dir, feature_name)
    if data is None:
        for sid in active_sids:
            store.unregister_session(sid)
        return len(active_sids)

    # Mark all active session entries as abandoned (covers stale JSON sessions too)
    abandoned_count = 0
    for s in data.get("sessions", []):
        if s.get("status") == "active":
            s["status"] = "abandoned"
            s["abandoned_at"] = now
            abandoned_count += 1

    data["session_id"] = None
    store.write_feature(project_dir, feature_name, data)

    # Unregister in-memory sessions
    for sid in active_sids:
        store.unregister_session(sid)

    return abandoned_count
```

- [ ] **Step 4: Register `feature_abandon_sessions` MCP tool in `register_tools`**

Inside the `register_tools` function in `mcp_tools.py`, add this tool after `feature_add_milestone` (before the closing of the function):

```python
    @mcp.tool()
    def feature_abandon_sessions(project_dir: str, feature_name: str) -> str:
        """Abandon all active sessions for a feature, clearing any conflict lock.
        The feature remains active and can be resumed cleanly afterward."""
        try:
            pdir = store.ensure_project_dir(project_dir)
        except ValueError as e:
            return json.dumps({"error": str(e)})

        data = store.read_feature(pdir, feature_name)
        if not data:
            return json.dumps({"error": f"Feature '{feature_name}' not found"})

        count = _abandon_all_sessions(store, pdir, feature_name)
        return json.dumps({
            "status": "ok",
            "feature_name": feature_name,
            "abandoned_count": count,
        })
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
cd feature-mcp && .venv/Scripts/python -m pytest tests/test_tools.py -k "abandon" -v
```

Expected: 6 PASSED.

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
cd feature-mcp && .venv/Scripts/python -m pytest tests/ -v
```

Expected: All existing tests still pass.

- [ ] **Step 7: Commit**

```bash
cd M:/bridgecrew
git add feature-mcp/mcp_tools.py feature-mcp/tests/test_tools.py
git commit -m "feat(feature-mcp): add feature_abandon_sessions MCP tool"
```

---

## Task 2: REST endpoint for abandon-sessions

**Files:**
- Modify: `feature-mcp/rest_api.py`
- Modify: `feature-mcp/tests/test_rest_api.py`

- [ ] **Step 1: Write failing tests**

Append to `feature-mcp/tests/test_rest_api.py`:

```python
def _active_feat_data(name, session_id):
    from feature_store import _now_iso
    now = _now_iso()
    return {
        "name": name, "status": "active", "session_id": session_id,
        "sessions": [{"session_id": session_id, "session_start": now,
                       "source": "cli", "status": "active"}],
        "milestones": [], "started_at": now, "completed_at": None,
        "total_cost_usd": 0.0, "total_input_tokens": 0, "total_output_tokens": 0,
    }


def test_abandon_sessions_endpoint_clears_sessions(client):
    c, store, tmp_project = client
    data = _active_feat_data("locked", "sess-stale")
    store.write_feature(tmp_project, "locked", data)
    store.register_session(tmp_project, "sess-stale", "locked")

    r = c.post(f"/api/projects/{_encode(tmp_project)}/features/locked/abandon-sessions")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["abandoned_count"] >= 1
    # Session removed from in-memory registry
    assert store.get_session_feature(tmp_project, "sess-stale") is None
    # session_id cleared in JSON
    feat = store.read_feature(tmp_project, "locked")
    assert feat["session_id"] is None


def test_abandon_sessions_endpoint_feature_not_found(client):
    c, store, tmp_project = client
    r = c.post(f"/api/projects/{_encode(tmp_project)}/features/ghost/abandon-sessions")
    assert r.status_code == 404


def test_abandon_sessions_endpoint_unknown_project(client):
    c, store, tmp_project = client
    r = c.post(f"/api/projects/{_encode('/nope')}/features/any/abandon-sessions")
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd feature-mcp && .venv/Scripts/python -m pytest tests/test_rest_api.py -k "abandon" -v
```

Expected: 3 failures with 404/405 (route doesn't exist yet).

- [ ] **Step 3: Add the endpoint to `rest_api.py`**

Add this import at the top of `rest_api.py` (update the existing import line):

```python
from mcp_tools import _conflict_response, _abandon_session, _abandon_all_sessions, _render_summary
```

Then add the new endpoint inside `create_api_router`, after the existing `/milestone` endpoint (before `return router`):

```python
    @router.post("/projects/{encoded_path:path}/features/{feature_name}/abandon-sessions")
    def post_abandon_sessions(encoded_path: str, feature_name: str):
        project_dir_str = unquote(encoded_path)
        try:
            pdir = store.ensure_project_dir(project_dir_str)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"Unknown project: {project_dir_str}")

        data = store.read_feature(pdir, feature_name)
        if not data:
            raise HTTPException(status_code=404, detail=f"Feature '{feature_name}' not found")

        count = _abandon_all_sessions(store, pdir, feature_name)
        return {"status": "ok", "feature_name": feature_name, "abandoned_count": count}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd feature-mcp && .venv/Scripts/python -m pytest tests/test_rest_api.py -k "abandon" -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Run full test suite**

```bash
cd feature-mcp && .venv/Scripts/python -m pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
cd M:/bridgecrew
git add feature-mcp/rest_api.py feature-mcp/tests/test_rest_api.py
git commit -m "feat(feature-mcp): add REST endpoint for abandon-sessions"
```

---

## Task 3: `mcp_client.py` async function

**Files:**
- Modify: `core/mcp_client.py`

No automated test — `mcp_client.py` has no test file, and mocking httpx for a thin wrapper adds no value.

- [ ] **Step 1: Add `abandon_feature_sessions` to `core/mcp_client.py`**

In `core/mcp_client.py`, add after the `post_cost` function:

```python
async def abandon_feature_sessions(project_dir: Path, feature_name: str) -> bool:
    """Abandon all active sessions for a feature. Returns True on success."""
    from feature_store import to_snake as _to_snake  # noqa: local import to avoid circular deps
    encoded_name = _to_snake(feature_name)
    url = f"{MCP_BASE}/api/projects/{_encode(project_dir)}/features/{encoded_name}/abandon-sessions"
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.post(url)
            return r.status_code == 200
        except Exception as exc:
            logger.warning("feature-mcp abandon_feature_sessions failed: %s", exc)
            return False
```

**Note on the URL:** The feature name in the URL path must be snake_case (matching the filename convention used by `feature_store._feature_path`). `to_snake("test-feature-closure")` → `"test_feature_closure"`. The REST endpoint receives the raw path segment and looks up the feature by that name, so we snake-case it here to match what the server stored.

Wait — actually looking at the REST endpoint: `feature_name` in the path is passed directly to `store.read_feature(pdir, feature_name)` which calls `_feature_path(project_dir, name)` which applies `to_snake`. So the REST endpoint already applies `to_snake` when looking up the file. The URL segment can be the display name or snake_case — both work. Use the display name (no transformation needed at the client level) to keep it simple. Remove the `to_snake` import.

Corrected implementation:

```python
async def abandon_feature_sessions(project_dir: Path, feature_name: str) -> bool:
    """Abandon all active sessions for a feature. Returns True on success."""
    url = f"{MCP_BASE}/api/projects/{_encode(project_dir)}/features/{feature_name}/abandon-sessions"
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.post(url)
            return r.status_code == 200
        except Exception as exc:
            logger.warning("feature-mcp abandon_feature_sessions failed: %s", exc)
            return False
```

- [ ] **Step 2: Commit**

```bash
cd M:/bridgecrew
git add core/mcp_client.py
git commit -m "feat: add abandon_feature_sessions to mcp_client"
```

---

## Task 4: Discord `/abandon-feature-sessions` command

**Files:**
- Modify: `discord_cogs/features.py`

- [ ] **Step 1: Add UI classes to `discord_cogs/features.py`**

Find the `# ── Cog ───` section comment (around line 354). Insert the new UI classes immediately before it:

```python
# ── Abandon Feature Sessions UI ──────────────────────────────────────────────

class AbandonSessionsSelect(discord.ui.Select):
    """Dropdown of features that have at least one active session."""

    def __init__(self, features_with_sessions: list[dict], project_dir: Path, bot):
        options = []
        for f in features_with_sessions[:25]:
            active_count = sum(
                1 for s in f.get("sessions", []) if s.get("status") == "active"
            )
            options.append(discord.SelectOption(
                label=f["name"],
                value=f["name"],
                description=f"{active_count} active session(s)",
            ))
        super().__init__(placeholder="Choose a feature...", options=options)
        self.project_dir = project_dir
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        name = self.values[0]
        view = AbandonSessionsConfirmView(name, self.project_dir, self.bot)
        await interaction.response.edit_message(
            content=(
                f"Abandon all active sessions for **`{name}`**?\n"
                "The feature stays active and can be resumed without a conflict error."
            ),
            view=view,
        )


class AbandonSessionsSelectView(discord.ui.View):
    def __init__(self, features_with_sessions: list[dict], project_dir: Path, bot):
        super().__init__(timeout=60)
        self.add_item(AbandonSessionsSelect(features_with_sessions, project_dir, bot))


class AbandonSessionsConfirmView(discord.ui.View):
    def __init__(self, feature_name: str, project_dir: Path, bot):
        super().__init__(timeout=60)
        self.feature_name = feature_name
        self.project_dir = project_dir
        self.bot = bot

    @discord.ui.button(label="Abandon Sessions", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        from core.mcp_client import abandon_feature_sessions as _abandon
        success = await _abandon(self.project_dir, self.feature_name)
        if success:
            await interaction.response.edit_message(
                content=f"Cleared active sessions for **`{self.feature_name}`**. You can now resume it without a conflict.",
                view=None,
            )
        else:
            await interaction.response.edit_message(
                content="Failed to contact the feature-mcp server. Try again or use `/restart-server`.",
                view=None,
            )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Cancelled.", view=None)
```

- [ ] **Step 2: Add the slash command to `FeaturesCog`**

Inside the `FeaturesCog` class, add after the `discard_feature` command (before `list_features`):

```python
    @captains_only()
    @app_commands.command(
        name="abandon-feature-sessions",
        description="Clear stale session locks on a feature so it can be resumed without a conflict",
    )
    async def abandon_feature_sessions(self, interaction: discord.Interaction) -> None:
        project, project_dir = self._resolve_project(interaction)
        if not project:
            await interaction.response.send_message(
                "Use this command inside a project thread.", ephemeral=True
            )
            return

        from core.mcp_client import get_features as _get_features
        features = await _get_features(project_dir)
        features_with_sessions = [
            f for f in features
            if any(s.get("status") == "active" for s in f.get("sessions", []))
        ]

        if not features_with_sessions:
            await interaction.response.send_message(
                "No features with active sessions — nothing to abandon.",
                ephemeral=True,
            )
            return

        view = AbandonSessionsSelectView(features_with_sessions, project_dir, self.bot)
        await interaction.response.send_message(
            "Pick a feature to clear its active sessions:",
            view=view,
            ephemeral=True,
        )
```

- [ ] **Step 3: Verify the bot starts without errors**

Start the bot and check for import or syntax errors:

```bash
cd M:/bridgecrew && python -c "import discord_cogs.features; print('OK')"
```

Expected output: `OK`

- [ ] **Step 4: Commit**

```bash
cd M:/bridgecrew
git add discord_cogs/features.py
git commit -m "feat: add /abandon-feature-sessions Discord slash command"
```

---

## Self-Review Checklist

- [x] `_abandon_all_sessions` helper covers both in-memory and stale JSON sessions
- [x] REST endpoint imports `_abandon_all_sessions` from `mcp_tools`
- [x] `mcp_client.abandon_feature_sessions` URL matches REST route pattern
- [x] Discord command filters to features with active sessions only
- [x] All 4 files in the spec are covered
- [x] No TBDs or placeholders
- [x] Type signatures consistent across tasks (`feature_name: str`, returns `int` / `bool` / JSON string)
- [x] `AbandonSessionsConfirmView` imports `abandon_feature_sessions` locally (avoids circular import at module level — consistent with how `complete_feature` imports `get_session_feature` locally in `features.py`)
