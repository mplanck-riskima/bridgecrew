# Project Maintainers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-project scheduled maintainers that check web app logs, detect issues, and apply fixes autonomously, dispatched via the existing APScheduler + Discord bot pipeline.

**Architecture:** New `project_maintainers` MongoDB collection with a dedicated FastAPI router. APScheduler is extended to load maintainer jobs alongside existing scheduled tasks. The bot parses a new `[maintainer-run:N]` marker to propagate per-run activity log TTLs. A new Maintainer tab in the dashboard ProjectDetail page provides the full CRUD UI.

**Tech Stack:** Python 3.11, FastAPI, PyMongo, APScheduler, React 19, TypeScript, Tailwind/LCARS theme

---

## File Map

```
NEW
  dashboard/backend/app/routers/maintainers.py   — CRUD + dispatch + prompt builder
  dashboard/frontend/src/components/MaintainerTab.tsx  — Maintainer tab UI component

MODIFIED
  dashboard/backend/app/db.py                    — project_maintainers_col() + expires_at TTL index
  dashboard/backend/app/routers/activity.py      — ttl_days field on POST /api/activity
  dashboard/backend/app/routers/projects.py      — discord_channel_id field on ProjectUpdate
  dashboard/backend/app/scheduler.py             — load maintainer jobs alongside schedule tasks
  dashboard/backend/app/main.py                  — register maintainers router
  dashboard/frontend/src/lib/types.ts            — ProjectMaintainer interface
  dashboard/frontend/src/lib/api.ts              — maintainer API methods
  dashboard/frontend/src/pages/ProjectDetail.tsx — add Maintainer tab
  core/bridgecrew_client.py                      — add update_project() + ttl_days on report_activity()
  discord_cogs/claude_prompt.py                  — parse [maintainer-run:N], propagate TTL, auto-register channel
```

---

## Task 1: DB accessor + TTL indexes

**Files:**
- Modify: `dashboard/backend/app/db.py`

- [ ] **Step 1: Add `project_maintainers_col()` and `expires_at` TTL index to `activity_col()`**

Open `dashboard/backend/app/db.py`. The current file ends at line 57. Add the following to the end:

```python
def project_maintainers_col() -> Collection:
    return get_db()["project_maintainers"]


def _ensure_activity_expires_at_index() -> None:
    """Sparse TTL index on expires_at for per-maintainer-run retention."""
    col = get_db()["activity"]
    try:
        col.create_index(
            [("expires_at", ASCENDING)],
            expireAfterSeconds=0,
            sparse=True,
            background=True,
        )
    except OperationFailure:
        pass  # Index already exists with same options — no action needed
```

Also update `activity_col()` to call `_ensure_activity_expires_at_index()` after creating the standard TTL index:

```python
def activity_col() -> Collection:
    col = get_db()["activity"]
    try:
        col.create_index([("created_at", ASCENDING)], expireAfterSeconds=604800, background=True)
    except OperationFailure:
        col.drop_index("created_at_1")
        col.create_index([("created_at", ASCENDING)], expireAfterSeconds=604800, background=True)
    _ensure_activity_expires_at_index()
    return col
```

- [ ] **Step 2: Verify syntax**

```bash
cd M:/bridgecrew/dashboard/backend
python -c "from app.db import project_maintainers_col, activity_col; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add dashboard/backend/app/db.py
git commit -m "feat: add project_maintainers_col and expires_at TTL index for activity"
```

---

## Task 2: Activity endpoint — ttl_days support

**Files:**
- Modify: `dashboard/backend/app/routers/activity.py`

- [ ] **Step 1: Write the failing test**

Create `dashboard/backend/tests/test_activity_ttl.py`:

```python
"""Test that POST /api/activity accepts ttl_days and writes expires_at."""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient


def _make_app():
    from fastapi import FastAPI
    from app.routers.activity import router
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_activity_without_ttl_has_no_expires_at():
    inserted = {}

    def fake_insert(doc):
        inserted.update(doc)
        m = MagicMock()
        m.inserted_id = "abc123"
        return m

    with patch("app.routers.activity.activity_col") as mock_col:
        mock_col.return_value.insert_one.side_effect = fake_insert
        client = TestClient(_make_app())
        resp = client.post("/api/activity", json={
            "project_id": "proj1", "role": "user", "author": "Alice", "content": "hi"
        })
    assert resp.status_code == 201
    assert "expires_at" not in inserted


def test_activity_with_ttl_sets_expires_at():
    inserted = {}

    def fake_insert(doc):
        inserted.update(doc)
        m = MagicMock()
        m.inserted_id = "abc123"
        return m

    with patch("app.routers.activity.activity_col") as mock_col:
        mock_col.return_value.insert_one.side_effect = fake_insert
        client = TestClient(_make_app())
        resp = client.post("/api/activity", json={
            "project_id": "proj1", "role": "user", "author": "Alice",
            "content": "hi", "ttl_days": 14
        })
    assert resp.status_code == 201
    assert "expires_at" in inserted
    delta = inserted["expires_at"] - inserted["created_at"]
    assert 13 < delta.days < 15
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd M:/bridgecrew/dashboard/backend
python -m pytest tests/test_activity_ttl.py -v
```
Expected: FAIL — `ttl_days` not a recognized field

- [ ] **Step 3: Add `ttl_days` to `ActivityCreate` and set `expires_at` in `ingest_activity`**

In `dashboard/backend/app/routers/activity.py`, update the imports to add `timedelta`:

```python
from datetime import datetime, timedelta, timezone
```

Update `ActivityCreate`:

```python
class ActivityCreate(BaseModel):
    project_id: str
    role: str          # "user" | "assistant"
    author: str        # Discord username or "Claude"
    content: str
    feature_name: str | None = None
    ttl_days: int | None = None
```

Update `ingest_activity`:

```python
@router.post("/activity", status_code=201)
def ingest_activity(body: ActivityCreate) -> dict:
    now = datetime.now(timezone.utc)
    doc = {
        "project_id": body.project_id,
        "role": body.role,
        "author": body.author,
        "content": body.content[:CONTENT_LIMIT],
        "feature_name": body.feature_name,
        "created_at": now,
    }
    if body.ttl_days is not None:
        doc["expires_at"] = now + timedelta(days=body.ttl_days)
    result = activity_col().insert_one(doc)
    doc["_id"] = result.inserted_id
    return _to_out(doc)
```

- [ ] **Step 4: Run tests**

```bash
cd M:/bridgecrew/dashboard/backend
python -m pytest tests/test_activity_ttl.py -v
```
Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/backend/app/routers/activity.py dashboard/backend/tests/test_activity_ttl.py
git commit -m "feat: add ttl_days to POST /api/activity for per-maintainer-run retention"
```

---

## Task 3: Add `discord_channel_id` to project model

**Files:**
- Modify: `dashboard/backend/app/routers/projects.py`

- [ ] **Step 1: Add `discord_channel_id` to `ProjectUpdate`**

In `dashboard/backend/app/routers/projects.py`, update `ProjectUpdate`:

```python
class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    prompt_template_id: str | None = None
    discord_channel_id: str | None = None
```

- [ ] **Step 2: Verify the field is accepted by running the app**

```bash
cd M:/bridgecrew/dashboard/backend
python -c "from app.routers.projects import ProjectUpdate; p = ProjectUpdate(discord_channel_id='123456'); print(p.discord_channel_id)"
```
Expected: `123456`

- [ ] **Step 3: Commit**

```bash
git add dashboard/backend/app/routers/projects.py
git commit -m "feat: add discord_channel_id to ProjectUpdate for maintainer dispatch"
```

---

## Task 4: Maintainers backend router

**Files:**
- Create: `dashboard/backend/app/routers/maintainers.py`
- Modify: `dashboard/backend/app/main.py`

- [ ] **Step 1: Write the failing test**

Create `dashboard/backend/tests/test_maintainers.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd M:/bridgecrew/dashboard/backend
python -m pytest tests/test_maintainers.py -v
```
Expected: FAIL — module not found

- [ ] **Step 3: Create `dashboard/backend/app/routers/maintainers.py`**

```python
"""Project maintainer CRUD, dispatch, and prompt builder."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import scheduler as sched
from app.db import project_maintainers_col, projects_col
from app.routers.schedules import _dispatch_to_discord, _get_bot_id

log = logging.getLogger(__name__)

router = APIRouter(tags=["maintainers"])


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


class MaintainerCreate(BaseModel):
    project_id: str
    name: str
    cron_expr: str
    enabled: bool = True
    log_sources: str
    detection_instructions: str
    fix_instructions: str
    log_ttl_days: int = 7


class MaintainerUpdate(BaseModel):
    name: str | None = None
    cron_expr: str | None = None
    enabled: bool | None = None
    log_sources: str | None = None
    detection_instructions: str | None = None
    fix_instructions: str | None = None
    log_ttl_days: int | None = None


@router.get("/maintainers")
def list_maintainers(project_id: str) -> list[dict]:
    """Return all maintainers for a project."""
    return [_serialize(doc) for doc in project_maintainers_col().find({"project_id": project_id})]


@router.post("/maintainers", status_code=201)
async def create_maintainer(body: MaintainerCreate) -> dict:
    """Create a new project maintainer."""
    doc = {
        "project_id": body.project_id,
        "name": body.name,
        "cron_expr": body.cron_expr,
        "enabled": body.enabled,
        "log_sources": body.log_sources,
        "detection_instructions": body.detection_instructions,
        "fix_instructions": body.fix_instructions,
        "log_ttl_days": body.log_ttl_days,
        "last_run": None,
        "last_status": "unknown",
        "created_at": datetime.now(UTC),
    }
    result = project_maintainers_col().insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    sched.reload_schedules()
    return doc


@router.put("/maintainers/{maintainer_id}")
async def update_maintainer(maintainer_id: str, body: MaintainerUpdate) -> dict:
    """Update a project maintainer."""
    try:
        oid = ObjectId(maintainer_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid maintainer ID")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = project_maintainers_col().update_one({"_id": oid}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Maintainer not found")

    doc = project_maintainers_col().find_one({"_id": oid})
    sched.reload_schedules()
    return _serialize(doc)


@router.delete("/maintainers/{maintainer_id}", status_code=204)
async def delete_maintainer(maintainer_id: str) -> None:
    """Delete a project maintainer."""
    try:
        oid = ObjectId(maintainer_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid maintainer ID")
    result = project_maintainers_col().delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Maintainer not found")
    sched.reload_schedules()


@router.post("/maintainers/{maintainer_id}/trigger")
async def trigger_maintainer(maintainer_id: str) -> dict:
    """Manually fire a maintainer run."""
    try:
        oid = ObjectId(maintainer_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid maintainer ID")

    task = project_maintainers_col().find_one({"_id": oid})
    if task is None:
        raise HTTPException(status_code=404, detail="Maintainer not found")

    status, detail = await _run_maintainer(task)
    result: dict = {"status": status}
    if detail:
        result["detail"] = detail
    return result


def _build_prompt(project_name: str, maintainer: dict) -> str:
    """Build the dispatch prompt from maintainer config."""
    ttl = maintainer.get("log_ttl_days", 7)
    return (
        f"You are the automated maintainer for project {project_name}.\n\n"
        f"Log sources to check:\n{maintainer['log_sources']}\n\n"
        f"How to detect if something went wrong:\n{maintainer['detection_instructions']}\n\n"
        f"How to fix issues when found:\n{maintainer['fix_instructions']}\n\n"
        f"Review the logs, apply the detection criteria, fix any issues found, "
        f"and report your findings.\n\n"
        f"[scheduled-order][maintainer-run:{ttl}]"
    )


async def _run_maintainer(task: dict) -> tuple[str, str]:
    """Core dispatch logic for a maintainer run."""
    project_id = task.get("project_id", "")
    project = projects_col().find_one({"project_id": project_id}, {"_id": 0})
    if project is None:
        log.warning("Maintainer %s: project %s not found", task.get("_id"), project_id)
        return "failed", f"project {project_id} not found"

    project_name = project.get("name", project_id)
    channel_id = project.get("discord_channel_id", "")
    if not channel_id:
        from app.config import settings
        channel_id = settings.DISCORD_CHANNEL_ID
    if not channel_id:
        return "failed", "no discord_channel_id on project and DISCORD_CHANNEL_ID not configured"

    bot_id = await _get_bot_id()
    mention = f"<@{bot_id}> " if bot_id else ""
    prompt = _build_prompt(project_name, task)
    full_content = f"{mention}{prompt}"

    status, detail = await _dispatch_to_discord(channel_id, full_content)

    project_maintainers_col().update_one(
        {"_id": task["_id"]},
        {"$set": {"last_run": datetime.now(UTC), "last_status": status}},
    )
    return status, detail
```

- [ ] **Step 4: Run tests**

```bash
cd M:/bridgecrew/dashboard/backend
python -m pytest tests/test_maintainers.py -v
```
Expected: 3 tests PASS

- [ ] **Step 5: Register router in `main.py`**

In `dashboard/backend/app/main.py`, add the import:

```python
from app.routers import activity, auth, costs, features, maintainers, projects, prompts, schedules
```

Add the router registration after the `schedules` line:

```python
app.include_router(maintainers.router, prefix="/api", dependencies=_auth)
```

- [ ] **Step 6: Verify the app starts**

```bash
cd M:/bridgecrew/dashboard/backend
python -c "from app.main import app; print('OK')"
```
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add dashboard/backend/app/routers/maintainers.py dashboard/backend/app/main.py dashboard/backend/tests/test_maintainers.py
git commit -m "feat: add project maintainers router with CRUD, dispatch, and prompt builder"
```

---

## Task 5: Extend scheduler for maintainer jobs

**Files:**
- Modify: `dashboard/backend/app/scheduler.py`

- [ ] **Step 1: Write the failing test**

Create `dashboard/backend/tests/test_maintainer_scheduler.py`:

```python
"""Test that reload_schedules loads maintainer jobs into APScheduler."""
from unittest.mock import patch, MagicMock
from bson import ObjectId


def _fake_maintainer(cron="0 9 * * *"):
    return {
        "_id": ObjectId("507f1f77bcf86cd799439011"),
        "name": "Daily Check",
        "cron_expr": cron,
        "enabled": True,
        "project_id": "proj1",
    }


def test_maintainer_job_added_to_scheduler():
    from app.scheduler import reload_schedules, get_scheduler

    with patch("app.scheduler.scheduled_tasks_col") as stc, \
         patch("app.scheduler.project_maintainers_col") as pmc:
        stc.return_value.find.return_value = []
        pmc.return_value.find.return_value = [_fake_maintainer()]

        reload_schedules()

    scheduler = get_scheduler()
    job_ids = [job.id for job in scheduler.get_jobs()]
    assert any(jid.startswith("maintainer:") for jid in job_ids)


def test_invalid_maintainer_cron_is_skipped():
    from app.scheduler import reload_schedules, get_scheduler

    with patch("app.scheduler.scheduled_tasks_col") as stc, \
         patch("app.scheduler.project_maintainers_col") as pmc:
        stc.return_value.find.return_value = []
        pmc.return_value.find.return_value = [_fake_maintainer(cron="bad cron")]

        reload_schedules()

    scheduler = get_scheduler()
    job_ids = [job.id for job in scheduler.get_jobs()]
    assert not any(jid.startswith("maintainer:") for jid in job_ids)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd M:/bridgecrew/dashboard/backend
python -m pytest tests/test_maintainer_scheduler.py -v
```
Expected: FAIL — `project_maintainers_col` not imported

- [ ] **Step 3: Update `scheduler.py`**

Add `_fire_maintainer` function and extend `reload_schedules()` in `dashboard/backend/app/scheduler.py`.

After the existing `_fire_task` function (line ~40), add:

```python
async def _fire_maintainer(maintainer_id: str) -> None:
    """Load maintainer from DB and dispatch. Called by APScheduler."""
    from bson import ObjectId

    from app.db import project_maintainers_col
    from app.routers.maintainers import _run_maintainer

    task = project_maintainers_col().find_one({"_id": ObjectId(maintainer_id)})
    if task is None:
        log.warning("Maintainer %s not found in DB — skipping", maintainer_id)
        return
    if not task.get("enabled", False):
        log.warning("Maintainer %s fired but is disabled — skipping", maintainer_id)
        return

    log.info("Auto-firing maintainer: %s", task.get("name", maintainer_id))
    status, detail = await _run_maintainer(task)
    log.info("Maintainer %s result: %s %s", maintainer_id, status, detail)
```

In `reload_schedules()`, after the existing `for task in tasks:` loop (after line ~86), add:

```python
    # Load maintainer jobs
    from app.db import project_maintainers_col
    maintainers = list(project_maintainers_col().find({"enabled": True}))
    for maintainer in maintainers:
        m_id = str(maintainer["_id"])
        cron_expr = maintainer.get("cron_expr", "").strip()
        if not cron_expr:
            continue
        try:
            parts = cron_expr.split()
            if len(parts) != 5:
                raise ValueError(f"expected 5 fields, got {len(parts)}")
            minute, hour, day, month, day_of_week = parts
            trigger = CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                timezone="America/Los_Angeles",
            )
            scheduler.add_job(
                _fire_maintainer,
                trigger=trigger,
                args=[m_id],
                id=f"maintainer:{m_id}",
                name=maintainer.get("name", m_id),
                replace_existing=True,
                misfire_grace_time=60,
            )
            log.info("Scheduled maintainer '%s' (%s)", maintainer.get("name"), cron_expr)
        except Exception as exc:
            log.warning("Skipping maintainer %s — invalid cron '%s': %s", m_id, cron_expr, exc)

    log.info("Scheduler reload complete: %d job(s) active", len(scheduler.get_jobs()))
```

Also remove the `log.info("Scheduler reload complete...")` line that currently exists at the end of the schedule loop (it's now at the end of the maintainer loop).

- [ ] **Step 4: Run tests**

```bash
cd M:/bridgecrew/dashboard/backend
python -m pytest tests/test_maintainer_scheduler.py -v
```
Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/backend/app/scheduler.py dashboard/backend/tests/test_maintainer_scheduler.py
git commit -m "feat: extend scheduler to load and fire project maintainer jobs"
```

---

## Task 6: `bridgecrew_client` — add `update_project` and `ttl_days` on `report_activity`

**Files:**
- Modify: `core/bridgecrew_client.py`

- [ ] **Step 1: Add `update_project` function**

In `core/bridgecrew_client.py`, after `assign_project_persona` (around line 278), add:

```python
def update_project(project_id: str, updates: dict) -> bool:
    """PATCH a project's fields via PUT /api/projects/{id}. Returns True on success."""
    if not _enabled() or not project_id:
        return False
    try:
        resp = httpx.put(
            f"{_API_URL}/api/projects/{project_id}",
            headers=_headers(),
            json=updates,
            timeout=5,
        )
        if resp.status_code == 200:
            return True
        log.warning("update_project: HTTP %s for project %s", resp.status_code, project_id)
    except Exception as exc:
        log.warning("update_project failed: %s", exc)
    return False
```

- [ ] **Step 2: Add `ttl_days` parameter to `report_activity`**

Update `report_activity` signature and payload:

```python
def report_activity(
    project_id: str,
    role: str,
    author: str,
    content: str,
    feature_name: str | None = None,
    ttl_days: int | None = None,
) -> None:
    """Log a user message or Claude response to the activity feed."""
    if not _enabled() or not project_id:
        return
    payload: dict = {
        "project_id": project_id,
        "role": role,
        "author": author,
        "content": content[:2000],
        "feature_name": feature_name,
    }
    if ttl_days is not None:
        payload["ttl_days"] = ttl_days
    try:
        resp = httpx.post(
            f"{_API_URL}/api/activity",
            headers=_headers(),
            json=payload,
            timeout=5,
        )
        if resp.status_code != 201:
            log.warning("report_activity: HTTP %s", resp.status_code)
    except Exception as exc:
        log.warning("report_activity failed: %s", exc)
```

- [ ] **Step 3: Verify syntax**

```bash
cd M:/bridgecrew
python -c "from core.bridgecrew_client import update_project, report_activity; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add core/bridgecrew_client.py
git commit -m "feat: add update_project and ttl_days param to report_activity in bridgecrew_client"
```

---

## Task 7: Bot — parse `[maintainer-run:N]`, propagate TTL, auto-register channel

**Files:**
- Modify: `discord_cogs/claude_prompt.py`

- [ ] **Step 1: Parse `[maintainer-run:N]` in `_process_prompt`**

In `discord_cogs/claude_prompt.py`, in `_process_prompt` (around line 1327), find the block that handles `[scheduled-order]` marker parsing:

```python
        is_scheduled = bool(_re.search(r"\[scheduled-order\]", prompt, _re.IGNORECASE))
        scheduled_persona_id = ""
        if is_scheduled:
            persona_match = _re.search(r"\[persona:([^\]]+)\]", prompt, _re.IGNORECASE)
            if persona_match:
                scheduled_persona_id = persona_match.group(1).strip()
            prompt = _re.sub(r"\s*\[scheduled-order\]\s*", "", prompt, flags=_re.IGNORECASE)
            prompt = _re.sub(r"\s*\[persona:[^\]]*\]\s*", "", prompt, flags=_re.IGNORECASE)
            prompt = prompt.strip()
```

Replace with:

```python
        is_scheduled = bool(_re.search(r"\[scheduled-order\]", prompt, _re.IGNORECASE))
        scheduled_persona_id = ""
        maintainer_ttl_days: int | None = None
        if is_scheduled:
            persona_match = _re.search(r"\[persona:([^\]]+)\]", prompt, _re.IGNORECASE)
            if persona_match:
                scheduled_persona_id = persona_match.group(1).strip()
            maintainer_match = _re.search(r"\[maintainer-run:(\d+)\]", prompt, _re.IGNORECASE)
            if maintainer_match:
                maintainer_ttl_days = int(maintainer_match.group(1))
            prompt = _re.sub(r"\s*\[scheduled-order\]\s*", "", prompt, flags=_re.IGNORECASE)
            prompt = _re.sub(r"\s*\[persona:[^\]]*\]\s*", "", prompt, flags=_re.IGNORECASE)
            prompt = _re.sub(r"\s*\[maintainer-run:\d+\]\s*", "", prompt, flags=_re.IGNORECASE)
            prompt = prompt.strip()
```

- [ ] **Step 2: Propagate `ttl_days` to both `_report_activity` calls**

There are two `_report_activity` calls in `_process_prompt`. The first is for the user message (around line 1435 in original, now ~1438 after our edits):

```python
            loop.run_in_executor(
                None,
                lambda: _report_activity(
                    project_id=bridgecrew_project_id,
                    role="user",
                    author=str(message.author),
                    content=prompt,
                    feature_name=feature.name if feature else None,
                ),
            )
```

Update to:

```python
            loop.run_in_executor(
                None,
                lambda ttl=maintainer_ttl_days: _report_activity(
                    project_id=bridgecrew_project_id,
                    role="user",
                    author=str(message.author),
                    content=prompt,
                    feature_name=feature.name if feature else None,
                    ttl_days=ttl,
                ),
            )
```

The second `_report_activity` call is for Claude's response (around line 1569 in original):

```python
            loop.run_in_executor(
                None,
                lambda: _report_activity(
                    project_id=bridgecrew_project_id,
                    role="assistant",
                    author="Claude",
                    content=response_text,
                    feature_name=feature.name if feature else None,
                ),
            )
```

Update to:

```python
            loop.run_in_executor(
                None,
                lambda ttl=maintainer_ttl_days: _report_activity(
                    project_id=bridgecrew_project_id,
                    role="assistant",
                    author="Claude",
                    content=response_text,
                    feature_name=feature.name if feature else None,
                    ttl_days=ttl,
                ),
            )
```

- [ ] **Step 3: Auto-register `discord_channel_id` on the project**

In `_process_prompt`, after the `bridgecrew_project_id` is resolved and just before the user message `report_activity` call, add:

```python
        # Auto-register the project's Discord channel ID (fire-and-forget, once per project)
        if bridgecrew_project_id and project and not state.get("discord_channel_registered"):
            from core.bridgecrew_client import update_project as _update_project
            _channel_id_str = str(message.channel.id)
            loop.run_in_executor(
                None,
                lambda: _update_project(bridgecrew_project_id, {"discord_channel_id": _channel_id_str}),
            )
            state["discord_channel_registered"] = True
            from core.state import save_project_state as _save_state
            _save_state(project_dir, state)
```

- [ ] **Step 4: Verify syntax**

```bash
cd M:/bridgecrew
python -c "import discord_cogs.claude_prompt; print('OK')"
```
Expected: `OK` (import-time syntax check passes)

- [ ] **Step 5: Commit**

```bash
git add discord_cogs/claude_prompt.py
git commit -m "feat: parse [maintainer-run:N] marker, propagate TTL to activity, auto-register channel"
```

---

## Task 8: Frontend — types and API client

**Files:**
- Modify: `dashboard/frontend/src/lib/types.ts`
- Modify: `dashboard/frontend/src/lib/api.ts`

- [ ] **Step 1: Add `ProjectMaintainer` interface to `types.ts`**

In `dashboard/frontend/src/lib/types.ts`, after the `ScheduledTask` interface, add:

```typescript
export interface ProjectMaintainer {
  id: string;
  project_id: string;
  name: string;
  cron_expr: string;
  enabled: boolean;
  log_sources: string;
  detection_instructions: string;
  fix_instructions: string;
  log_ttl_days: number;
  last_run: string | null;
  last_status: "dispatched" | "failed" | "skipped" | "unknown";
  created_at: string;
}
```

- [ ] **Step 2: Add maintainer API methods to `api.ts`**

In `dashboard/frontend/src/lib/api.ts`, add `ProjectMaintainer` to the import from types, then add maintainer methods to the `api` object after `triggerSchedule`:

```typescript
// Maintainers
getMaintainers: (projectId: string) =>
  request<ProjectMaintainer[]>(`/maintainers?project_id=${encodeURIComponent(projectId)}`),
createMaintainer: (data: Omit<ProjectMaintainer, "id" | "last_run" | "last_status" | "created_at">) =>
  request<ProjectMaintainer>("/maintainers", {
    method: "POST",
    body: JSON.stringify(data),
  }),
updateMaintainer: (id: string, data: Partial<ProjectMaintainer>) =>
  request<ProjectMaintainer>(`/maintainers/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  }),
deleteMaintainer: (id: string) =>
  request<void>(`/maintainers/${id}`, { method: "DELETE" }),
triggerMaintainer: (id: string) =>
  request<{ status: string }>(`/maintainers/${id}/trigger`, { method: "POST" }),
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd M:/bridgecrew/dashboard/frontend
npx tsc --noEmit
```
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add dashboard/frontend/src/lib/types.ts dashboard/frontend/src/lib/api.ts
git commit -m "feat: add ProjectMaintainer type and API client methods"
```

---

## Task 9: Frontend — Maintainer tab in ProjectDetail

**Files:**
- Create: `dashboard/frontend/src/components/MaintainerTab.tsx`
- Modify: `dashboard/frontend/src/pages/ProjectDetail.tsx`

- [ ] **Step 1: Create `MaintainerTab.tsx`**

Create `dashboard/frontend/src/components/MaintainerTab.tsx`:

```tsx
import { useState } from "react";
import cronstrue from "cronstrue";
import { api } from "@/lib/api";
import type { ProjectMaintainer } from "@/lib/types";
import CronInput from "@/components/CronInput";

function safeDescribe(expr: string): string {
  try { return cronstrue.toString(expr, { use24HourTimeFormat: false }); }
  catch { return ""; }
}

const STATUS_COLORS: Record<string, string> = {
  dispatched: "text-lcars-green",
  failed: "text-lcars-red",
  skipped: "text-lcars-amber",
  unknown: "text-lcars-muted",
};

const BLANK_FORM = {
  name: "",
  cron_expr: "0 9 * * *",
  enabled: true,
  log_sources: "",
  detection_instructions: "",
  fix_instructions: "",
  log_ttl_days: 7,
};

interface Props {
  projectId: string;
  maintainers: ProjectMaintainer[];
  onRefresh: () => void;
}

export default function MaintainerTab({ projectId, maintainers, onRefresh }: Props) {
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(BLANK_FORM);
  const [saving, setSaving] = useState(false);
  const [triggering, setTriggering] = useState<string | null>(null);
  const [triggerResult, setTriggerResult] = useState<Record<string, string>>({});

  function startCreate() {
    setForm(BLANK_FORM);
    setCreating(true);
    setEditingId(null);
  }

  function startEdit(m: ProjectMaintainer) {
    setForm({
      name: m.name,
      cron_expr: m.cron_expr,
      enabled: m.enabled,
      log_sources: m.log_sources,
      detection_instructions: m.detection_instructions,
      fix_instructions: m.fix_instructions,
      log_ttl_days: m.log_ttl_days,
    });
    setEditingId(m.id);
    setCreating(false);
  }

  function cancelForm() {
    setCreating(false);
    setEditingId(null);
  }

  async function saveForm() {
    setSaving(true);
    try {
      if (editingId) {
        await api.updateMaintainer(editingId, form);
      } else {
        await api.createMaintainer({ ...form, project_id: projectId });
      }
      cancelForm();
      onRefresh();
    } catch (e) {
      alert(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function deleteMaintainer(id: string) {
    if (!confirm("Delete this maintainer?")) return;
    try {
      await api.deleteMaintainer(id);
      onRefresh();
    } catch (e) {
      alert(String(e));
    }
  }

  async function runNow(id: string) {
    setTriggering(id);
    try {
      const result = await api.triggerMaintainer(id);
      setTriggerResult((prev) => ({ ...prev, [id]: result.status }));
      setTimeout(() => setTriggerResult((prev) => { const n = {...prev}; delete n[id]; return n; }), 4000);
      onRefresh();
    } catch (e) {
      alert(String(e));
    } finally {
      setTriggering(null);
    }
  }

  const showForm = creating || editingId !== null;
  const fieldCls = "w-full bg-lcars-panel border border-lcars-border text-lcars-text font-mono text-sm px-3 py-2 focus:outline-none focus:border-lcars-orange";
  const textareaCls = fieldCls + " resize-y min-h-[80px]";

  return (
    <div className="space-y-4">
      {!showForm && (
        <button
          onClick={startCreate}
          className="px-4 py-1.5 bg-lcars-orange text-black font-mono text-xs font-bold tracking-widest hover:bg-lcars-amber transition-colors"
        >
          + ADD MAINTAINER
        </button>
      )}

      {showForm && (
        <div className="bg-lcars-panel border border-lcars-border p-4 space-y-3">
          <div className="text-xs font-mono font-bold tracking-widest text-lcars-orange uppercase mb-2">
            {editingId ? "EDIT MAINTAINER" : "NEW MAINTAINER"}
          </div>

          <div>
            <label className="text-xs font-mono text-lcars-muted uppercase tracking-widest block mb-1">Name</label>
            <input className={fieldCls} value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="Daily Log Check" />
          </div>

          <div>
            <label className="text-xs font-mono text-lcars-muted uppercase tracking-widest block mb-1">Schedule</label>
            <CronInput value={form.cron_expr} onChange={(v) => setForm((f) => ({ ...f, cron_expr: v }))} />
          </div>

          <div>
            <label className="text-xs font-mono text-lcars-muted uppercase tracking-widest block mb-1">Log Sources</label>
            <textarea className={textareaCls} value={form.log_sources} onChange={(e) => setForm((f) => ({ ...f, log_sources: e.target.value }))} placeholder="Describe where to find logs: Railway dashboard, /api/logs endpoint, log file at /var/log/app.log, etc." />
          </div>

          <div>
            <label className="text-xs font-mono text-lcars-muted uppercase tracking-widest block mb-1">Detection Instructions</label>
            <textarea className={textareaCls} value={form.detection_instructions} onChange={(e) => setForm((f) => ({ ...f, detection_instructions: e.target.value }))} placeholder="How to determine if something went wrong: look for ERROR lines, 5xx responses, memory usage above 90%, etc." />
          </div>

          <div>
            <label className="text-xs font-mono text-lcars-muted uppercase tracking-widest block mb-1">Fix Instructions</label>
            <textarea className={textareaCls} value={form.fix_instructions} onChange={(e) => setForm((f) => ({ ...f, fix_instructions: e.target.value }))} placeholder="What to do when an issue is found: restart the service, roll back the last commit, send a notification, etc." />
          </div>

          <div>
            <label className="text-xs font-mono text-lcars-muted uppercase tracking-widest block mb-1">Log Retention (days)</label>
            <input type="number" min={1} max={365} className={fieldCls} value={form.log_ttl_days} onChange={(e) => setForm((f) => ({ ...f, log_ttl_days: parseInt(e.target.value) || 7 }))} />
          </div>

          <div className="flex items-center gap-2">
            <input type="checkbox" id="m-enabled" checked={form.enabled} onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))} />
            <label htmlFor="m-enabled" className="text-xs font-mono text-lcars-muted">Enabled</label>
          </div>

          <div className="flex gap-2 pt-1">
            <button onClick={saveForm} disabled={saving || !form.name || !form.cron_expr} className="px-4 py-1.5 bg-lcars-orange text-black font-mono text-xs font-bold tracking-widest hover:bg-lcars-amber transition-colors disabled:opacity-40">
              {saving ? "SAVING..." : "SAVE"}
            </button>
            <button onClick={cancelForm} className="px-4 py-1.5 border border-lcars-border text-lcars-muted font-mono text-xs hover:text-lcars-text transition-colors">
              CANCEL
            </button>
          </div>
        </div>
      )}

      {maintainers.length === 0 && !showForm && (
        <div className="text-lcars-muted font-mono text-sm p-4">
          NO MAINTAINERS CONFIGURED — ADD ONE TO START AUTOMATED LOG CHECKS
        </div>
      )}

      {maintainers.map((m) => (
        <div key={m.id} className="bg-lcars-panel border border-lcars-border p-4">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-lcars-cyan font-medium">{m.name}</span>
                <span className={`text-xs font-mono ${m.enabled ? "text-lcars-green" : "text-lcars-muted"}`}>
                  {m.enabled ? "ENABLED" : "DISABLED"}
                </span>
                <span className={`text-xs font-mono ${STATUS_COLORS[m.last_status]}`}>{m.last_status}</span>
              </div>
              <div className="text-xs font-mono text-lcars-muted mt-1">
                {safeDescribe(m.cron_expr) || m.cron_expr}
                {m.last_run && <span className="ml-3">last run: {new Date(m.last_run).toLocaleString()}</span>}
              </div>
              <div className="text-xs font-mono text-lcars-muted mt-1">
                retention: {m.log_ttl_days}d
              </div>
            </div>
            <div className="flex gap-2 shrink-0">
              {triggerResult[m.id] && (
                <span className={`text-xs font-mono self-center ${STATUS_COLORS[triggerResult[m.id]] ?? "text-lcars-muted"}`}>
                  {triggerResult[m.id]}
                </span>
              )}
              <button
                onClick={() => runNow(m.id)}
                disabled={triggering === m.id}
                className="px-2 py-1 text-xs font-mono border border-lcars-border text-lcars-cyan hover:border-lcars-cyan transition-colors disabled:opacity-40"
              >
                {triggering === m.id ? "..." : "RUN NOW"}
              </button>
              <button
                onClick={() => startEdit(m)}
                className="px-2 py-1 text-xs font-mono border border-lcars-border text-lcars-muted hover:text-lcars-text transition-colors"
              >
                EDIT
              </button>
              <button
                onClick={() => deleteMaintainer(m.id)}
                className="px-2 py-1 text-xs font-mono border border-lcars-red/40 text-lcars-red hover:border-lcars-red transition-colors"
              >
                DEL
              </button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Update `ProjectDetail.tsx`**

In `dashboard/frontend/src/pages/ProjectDetail.tsx`, update the `Tab` type and imports:

```typescript
import MaintainerTab from "@/components/MaintainerTab";
import type { ActivityEntry, Feature, FeatureCostBreakdown, Project, ProjectMaintainer, PromptTemplate } from "@/lib/types";

type Tab = "features" | "activity" | "maintainer";
```

Add maintainers state variable (after existing state declarations):

```typescript
const [maintainers, setMaintainers] = useState<ProjectMaintainer[]>([]);
```

In the `load()` function, add maintainer loading (after loading `activity`):

```typescript
const ms = await api.getMaintainers(p.project_id);
setMaintainers(ms);
```

Add a `loadMaintainers` helper called by `MaintainerTab` on refresh:

```typescript
async function loadMaintainers() {
  if (!project) return;
  try {
    const ms = await api.getMaintainers(project.project_id);
    setMaintainers(ms);
  } catch {
    // ignore
  }
}
```

Update the `tabs` array:

```typescript
const tabs: { key: Tab; label: string }[] = [
  { key: "features", label: "FEATURES" },
  { key: "activity", label: "RECENT ACTIVITY" },
  { key: "maintainer", label: "MAINTAINER" },
];
```

Add the maintainer tab panel after the `{tab === "activity" && ...}` block:

```tsx
{tab === "maintainer" && (
  <MaintainerTab
    projectId={p.project_id}
    maintainers={maintainers}
    onRefresh={loadMaintainers}
  />
)}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd M:/bridgecrew/dashboard/frontend
npx tsc --noEmit
```
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add dashboard/frontend/src/components/MaintainerTab.tsx dashboard/frontend/src/pages/ProjectDetail.tsx
git commit -m "feat: add Maintainer tab to ProjectDetail with full CRUD and Run Now"
```

---

## Self-Review Checklist (done inline)

- **Spec coverage:** All spec sections covered: data model (Task 1), API + scheduler (Tasks 4+5), activity TTL (Tasks 2+6+7), dashboard UI (Tasks 8+9), bot changes (Task 7).
- **Placeholders:** None — all code blocks are complete.
- **Type consistency:** `ProjectMaintainer` defined in Task 8 step 1, used in Task 9 step 2 and step 1. `MaintainerCreate`/`MaintainerUpdate` defined in Task 4 step 3. `_build_prompt` defined and tested in Task 4.
- **Scope:** 9 focused tasks, each independently committable.
