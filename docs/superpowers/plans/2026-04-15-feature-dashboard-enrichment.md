# Feature Dashboard Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register features in the dashboard MongoDB on start/complete, surface per-model cost breakdown per feature card, and display the rendered feature markdown on completed feature cards.

**Architecture:** Three layers — (1) dashboard backend gains a unique `feature_id` index, `markdown_content` field, and a new per-feature cost breakdown endpoint; (2) the Discord bot wires dashboard reporting into `run_feature_init_session` and `run_feature_complete_session` using a deterministic `"{project_name}:{feature_name}"` composite key (colon separator avoids URL path issues); (3) the frontend feature cards show per-model cost breakdown and a collapsible markdown panel for completed features. No `react-markdown` dependency — the feature .md format is readable as plaintext in a `<pre>` block.

**Tech Stack:** Python/FastAPI + PyMongo (dashboard backend), Python/discord.py (bot), React 19 + TypeScript + Tailwind (frontend)

---

### Task 1: Dashboard DB — Add indexes

**Files:**
- Modify: `dashboard/backend/app/db.py`

- [ ] **Step 1: Add unique index on `features.feature_id` and index on `cost_log.feature_id`**

Current `db.py` has no indexes on these collections. Replace the two accessor functions:

```python
def features_col() -> Collection:
    col = get_db()["features"]
    col.create_index([("feature_id", ASCENDING)], unique=True, background=True)
    return col


def cost_log_col() -> Collection:
    col = get_db()["cost_log"]
    col.create_index([("feature_id", ASCENDING)], background=True)
    return col
```

- [ ] **Step 2: Commit**

```bash
cd M:/bridgecrew
git add dashboard/backend/app/db.py
git commit -m "feat(dashboard): add feature_id indexes on features and cost_log collections"
```

---

### Task 2: Dashboard backend — `markdown_content` field + duplicate ID handling

**Files:**
- Modify: `dashboard/backend/app/routers/features.py`

- [ ] **Step 1: Add `DuplicateKeyError` import**

Add to the imports at the top of `routers/features.py`:

```python
from pymongo.errors import DuplicateKeyError
```

- [ ] **Step 2: Add `markdown_content` to `FeatureUpdate`**

Change `FeatureUpdate` (currently lines 29-37) to:

```python
class FeatureUpdate(BaseModel):
    """Payload the discord-Claude bot sends when updating / completing a feature."""
    status: str | None = None
    summary: str | None = None
    total_cost_usd: float | None = None
    git_branch: str | None = None
    session_id: str | None = None
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    markdown_content: str | None = None
```

- [ ] **Step 3: Handle duplicate `feature_id` in `create_feature`**

The unique index added in Task 1 means a second call with the same `feature_id` will raise `DuplicateKeyError`. Handle it gracefully (resume after bot restart may trigger this). Replace the `insert_one` + `return` block in `create_feature` (currently lines 107-110):

```python
    try:
        features_col().insert_one(doc)
        doc.pop("_id", None)
        return doc
    except DuplicateKeyError:
        existing = features_col().find_one({"feature_id": doc["feature_id"]}, {"_id": 0})
        return existing
```

- [ ] **Step 4: Verify manually (optional smoke test)**

With the dashboard running:
```bash
# First call — creates
curl -s -X POST http://localhost:8000/api/features \
  -H "Authorization: Bearer $BRIDGECREW_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"feature_id":"smoke:test-dup","project_id":"proj1","name":"test-dup"}' | python -m json.tool
# Second call — returns existing, no error
curl -s -X POST http://localhost:8000/api/features \
  -H "Authorization: Bearer $BRIDGECREW_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"feature_id":"smoke:test-dup","project_id":"proj1","name":"test-dup"}' | python -m json.tool
```
Expected: both calls return the same `feature_id`, no 500 error.

- [ ] **Step 5: Commit**

```bash
git add dashboard/backend/app/routers/features.py
git commit -m "feat(dashboard): add markdown_content to FeatureUpdate, handle duplicate feature_id on create"
```

---

### Task 3: Dashboard backend — Per-feature cost breakdown endpoint

**Files:**
- Modify: `dashboard/backend/app/routers/features.py`

- [ ] **Step 1: Import `cost_log_col`**

Change the existing db import line from:

```python
from app.db import features_col
```

to:

```python
from app.db import cost_log_col, features_col
```

- [ ] **Step 2: Add the endpoint**

Add this route immediately after the `get_feature` route (after line 73):

```python
@router.get("/features/{feature_id}/costs/breakdown")
def get_feature_cost_breakdown(feature_id: str) -> dict:
    """Return per-model cost breakdown for a specific feature."""
    pipeline = [
        {"$match": {"feature_id": feature_id}},
        {"$group": {
            "_id": "$model",
            "cost_usd": {"$sum": "$cost_usd"},
            "input_tokens": {"$sum": "$input_tokens"},
            "output_tokens": {"$sum": "$output_tokens"},
        }},
        {"$sort": {"cost_usd": -1}},
    ]
    rows = list(cost_log_col().aggregate(pipeline))
    by_model = {
        row["_id"]: {
            "cost_usd": row["cost_usd"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
        }
        for row in rows
        if row["_id"]
    }
    return {"by_model": by_model}
```

- [ ] **Step 3: Verify**

```bash
curl -s http://localhost:8000/api/features/bridgecrew:feature-stuff-on-pc/costs/breakdown
# Expected: {"by_model": {}} — or data if cost_log has matching entries
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/backend/app/routers/features.py
git commit -m "feat(dashboard): add GET /features/{feature_id}/costs/breakdown endpoint"
```

---

### Task 4: `bridgecrew_client.py` — Update `report_feature_started` and `report_feature_completed`

**Files:**
- Modify: `core/bridgecrew_client.py`

- [ ] **Step 1: Add `feature_id` param to `report_feature_started`**

Current signature (lines 66-72):
```python
def report_feature_started(
    project_id: str,
    feature_name: str,
    session_id: str,
    prompt_template_id: str = "",
    subdir: str = "",
) -> str | None:
```

New signature — add `feature_id: str = ""` before the optional params:
```python
def report_feature_started(
    project_id: str,
    feature_name: str,
    session_id: str,
    feature_id: str = "",
    prompt_template_id: str = "",
    subdir: str = "",
) -> str | None:
```

Update the `payload` dict (currently lines 79-85) to include `feature_id`:
```python
    payload = {
        "feature_id": feature_id,
        "project_id": project_id,
        "name": feature_name,
        "session_id": session_id,
        "prompt_template_id": prompt_template_id,
        "subdir": subdir or "",
    }
```

- [ ] **Step 2: Add `markdown_content` to `report_feature_completed`**

Current signature (lines 101-108):
```python
def report_feature_completed(
    feature_id: str,
    summary: str = "",
    total_cost_usd: float = 0.0,
    git_branch: str = "",
    total_input_tokens: int = 0,
    total_output_tokens: int = 0,
) -> None:
```

New signature:
```python
def report_feature_completed(
    feature_id: str,
    summary: str = "",
    total_cost_usd: float = 0.0,
    git_branch: str = "",
    total_input_tokens: int = 0,
    total_output_tokens: int = 0,
    markdown_content: str | None = None,
) -> None:
```

Add to the `payload` block (after the `total_output_tokens` check):
```python
    if markdown_content is not None:
        payload["markdown_content"] = markdown_content
```

- [ ] **Step 3: Commit**

```bash
git add core/bridgecrew_client.py
git commit -m "feat(bot): add feature_id to report_feature_started, markdown_content to report_feature_completed"
```

---

### Task 5: `claude_prompt.py` — Fix composite key for cost reporting

**Files:**
- Modify: `discord_cogs/claude_prompt.py` (around line 662)

- [ ] **Step 1: Find and replace the `_feature_bc_id` line**

Find (line ~662 inside `_run_stream`):
```python
                            _feature_bc_id = getattr(feature, "bridgecrew_feature_id", "") if feature else ""
```

Replace with:
```python
                            _feature_bc_id = f"{project_name}:{feature.name}" if (project_name and feature) else ""
```

- [ ] **Step 2: Commit**

```bash
git add discord_cogs/claude_prompt.py
git commit -m "fix(bot): use project:feature composite key for cost reporting instead of bridgecrew_feature_id"
```

---

### Task 6: `claude_prompt.py` — Wire `report_feature_started` on feature start

**Files:**
- Modify: `discord_cogs/claude_prompt.py` (inside `run_feature_init_session`, lines 924-952)

- [ ] **Step 1: Add dashboard registration after MCP start**

The current `_run()` closure inside `run_feature_init_session` (lines 924-952) ends with:
```python
        if last_sid:
            from core.mcp_client import (
                start_feature_session as _start_fs,
                resume_feature_session as _resume_fs,
            )
            if action == "start":
                await _start_fs(project_dir, last_sid, feature_name)
            else:
                await _resume_fs(project_dir, last_sid, feature_name)
        await self._worker(thread_id)
```

Replace the entire `_run()` closure (keep the `try/finally` for the system run label) with:
```python
        async def _run():
            try:
                last_sid, _, _ = await self._run_stream(
                    channel=channel,
                    runner=self.bot.claude_runner,
                    prompt=prompt,
                    project_dir=project_dir,
                    run_dir=project_dir,
                    thread_id=thread_id,
                    session_id=session_id,
                    resume=session_id is not None,
                    feature=None,
                )
            finally:
                self._system_run_labels.pop(thread_id, None)
            # Register the real CLI session UUID with the MCP server.
            if last_sid:
                from core.mcp_client import (
                    start_feature_session as _start_fs,
                    resume_feature_session as _resume_fs,
                )
                if action == "start":
                    await _start_fs(project_dir, last_sid, feature_name)
                else:
                    await _resume_fs(project_dir, last_sid, feature_name)
                # Register new features in the dashboard (start only — resume reuses existing record)
                if action == "start":
                    _project = self.bot.project_manager.get_project_by_thread(channel.id)
                    if _project:
                        from core.state import load_project_state as _lps_init
                        from core.bridgecrew_client import report_feature_started as _rfs
                        _state_init = _lps_init(project_dir)
                        _bc_project_id = _state_init.get("bridgecrew_project_id", "")
                        _composite_id = f"{_project.name}:{feature_name}"
                        _loop = asyncio.get_event_loop()
                        await _loop.run_in_executor(
                            None,
                            lambda: _rfs(
                                project_id=_bc_project_id,
                                feature_name=feature_name,
                                session_id=last_sid,
                                feature_id=_composite_id,
                            ),
                        )
            await self._worker(thread_id)
```

- [ ] **Step 2: Commit**

```bash
git add discord_cogs/claude_prompt.py
git commit -m "feat(bot): register new features in dashboard on start via report_feature_started"
```

---

### Task 7: `claude_prompt.py` — Wire `report_feature_completed` on feature complete

**Files:**
- Modify: `discord_cogs/claude_prompt.py` (inside `run_feature_complete_session._run()`, lines 1072-1102)

- [ ] **Step 1: Add dashboard completion report after state cleanup**

The current `_run()` closure ends with:
```python
                _cstate = _lps_c(project_dir)
                _cstate.pop("active_feature_name", None)
                _cstate.pop("pending_feature_op", None)
                _sps_c(project_dir, _cstate)
            finally:
                self._system_run_labels.pop(thread_id, None)
            await self._worker(thread_id)
```

Add the dashboard report block after `_sps_c(project_dir, _cstate)` and before the `finally`:
```python
                _cstate = _lps_c(project_dir)
                _cstate.pop("active_feature_name", None)
                _cstate.pop("pending_feature_op", None)
                _sps_c(project_dir, _cstate)
                # Report completion + markdown to dashboard
                _project = self.bot.project_manager.get_project_by_thread(channel.id)
                if _project:
                    from pathlib import Path as _Path
                    from core.mcp_client import get_features as _gf
                    from core.bridgecrew_client import report_feature_completed as _rfc
                    _composite_id = f"{_project.name}:{feature_name}"
                    _md_path = _Path(project_dir) / "features" / f"{feature_name}.md"
                    _md_content = None
                    try:
                        _md_content = _md_path.read_text(encoding="utf-8")
                    except Exception:
                        pass
                    _feats = await _gf(project_dir)
                    _feat_data = next((f for f in _feats if f.get("name") == feature_name), {})
                    _loop = asyncio.get_event_loop()
                    await _loop.run_in_executor(
                        None,
                        lambda md=_md_content, fd=_feat_data, cid=_composite_id: _rfc(
                            feature_id=cid,
                            total_cost_usd=fd.get("total_cost_usd", 0.0),
                            total_input_tokens=fd.get("total_input_tokens", 0),
                            total_output_tokens=fd.get("total_output_tokens", 0),
                            markdown_content=md,
                        ),
                    )
            finally:
                self._system_run_labels.pop(thread_id, None)
            await self._worker(thread_id)
```

Note: the lambda uses default argument binding (`md=_md_content, fd=_feat_data, cid=_composite_id`) to capture values at definition time, not at call time.

- [ ] **Step 2: Commit**

```bash
git add discord_cogs/claude_prompt.py
git commit -m "feat(bot): report feature completion and markdown to dashboard after feature_complete"
```

---

### Task 8: Frontend TypeScript — Types and API

**Files:**
- Modify: `dashboard/frontend/src/lib/types.ts`
- Modify: `dashboard/frontend/src/lib/api.ts`

- [ ] **Step 1: Add `markdown_content` to `Feature` and add `FeatureCostBreakdown` type**

In `types.ts`, update `Feature` (add `markdown_content` after `git_branch`):
```typescript
export interface Feature {
  feature_id: string;
  project_id: string;
  name: string;
  description: string;
  status: "active" | "completed" | "abandoned";
  session_id: string;
  prompt_template_id: string;
  subdir: string;
  total_cost_usd: number;
  total_input_tokens: number;
  total_output_tokens: number;
  summary: string | null;
  git_branch: string | null;
  markdown_content: string | null;
  created_at: string;
  completed_at: string | null;
}
```

Add `FeatureCostBreakdown` interface after `Feature`:
```typescript
export interface FeatureCostBreakdown {
  by_model: Record<string, {
    cost_usd: number;
    input_tokens: number;
    output_tokens: number;
  }>;
}
```

- [ ] **Step 2: Add `getFeatureCostBreakdown` to `api.ts`**

Import `FeatureCostBreakdown` in `api.ts` (add to the existing import):
```typescript
import type {
  ActivityEntry,
  AgentSummary,
  CostBreakdown,
  CostTimelineEntry,
  Feature,
  FeatureCostBreakdown,
  PaginatedResponse,
  PersonaDefinition,
  Project,
  PromptTemplate,
  ScheduledTask,
} from "./types";
```

Add to the `api` object after `deleteFeature`:
```typescript
  getFeatureCostBreakdown: (featureId: string) =>
    request<FeatureCostBreakdown>(`/features/${encodeURIComponent(featureId)}/costs/breakdown`),
```

- [ ] **Step 3: Commit**

```bash
cd M:/bridgecrew
git add dashboard/frontend/src/lib/types.ts dashboard/frontend/src/lib/api.ts
git commit -m "feat(frontend): add FeatureCostBreakdown type and getFeatureCostBreakdown API call"
```

---

### Task 9: Frontend UI — Feature card improvements

**Files:**
- Modify: `dashboard/frontend/src/pages/ProjectDetail.tsx`

- [ ] **Step 1: Add type imports and state**

Update the import line at the top:
```typescript
import type { ActivityEntry, Feature, FeatureCostBreakdown, Project, PromptTemplate } from "@/lib/types";
```

Add two new state variables inside `ProjectDetail` after the existing state declarations:
```typescript
  const [costBreakdowns, setCostBreakdowns] = useState<Record<string, FeatureCostBreakdown>>({});
  const [expandedMarkdown, setExpandedMarkdown] = useState<string | null>(null);
```

- [ ] **Step 2: Fetch cost breakdowns when features tab loads**

Add this `useEffect` after the polling effect (after line 70):
```typescript
  useEffect(() => {
    if (tab !== "features" || !project?.features?.length) return;
    project.features.forEach((f) => {
      api.getFeatureCostBreakdown(f.feature_id)
        .then((breakdown) => {
          setCostBreakdowns((prev) => ({ ...prev, [f.feature_id]: breakdown }));
        })
        .catch(() => {});
    });
  }, [tab, id, project]);
```

- [ ] **Step 3: Replace the single cost line with per-model breakdown**

Inside the `features.map((f) => ...)` block, find the cost display (currently lines 229-231):
```tsx
                    {f.total_cost_usd > 0 && (
                      <span className="text-lcars-green">{formatCurrency(f.total_cost_usd)}</span>
                    )}
```

Replace with:
```tsx
                    {costBreakdowns[f.feature_id] && Object.keys(costBreakdowns[f.feature_id].by_model).length > 0 ? (
                      <div className="flex flex-col gap-0.5">
                        {Object.entries(costBreakdowns[f.feature_id].by_model).map(([model, data]) => (
                          <span key={model} className="text-lcars-green">
                            {model.replace("claude-", "")} {formatCurrency(data.cost_usd)}
                          </span>
                        ))}
                      </div>
                    ) : f.total_cost_usd > 0 ? (
                      <span className="text-lcars-green">{formatCurrency(f.total_cost_usd)}</span>
                    ) : null}
```

- [ ] **Step 4: Add collapsible markdown panel for completed features**

Inside the `features.map((f) => ...)` block, after the closing `</div>` of the outer `flex items-start justify-between gap-4` row (after the delete button block, around line 263), add:
```tsx
              {f.status === "completed" && f.markdown_content && (
                <div className="mt-3 border-t border-lcars-border pt-3">
                  <button
                    onClick={() => setExpandedMarkdown(expandedMarkdown === f.feature_id ? null : f.feature_id)}
                    className="text-xs font-mono text-lcars-cyan hover:text-lcars-amber tracking-widest transition-colors"
                  >
                    {expandedMarkdown === f.feature_id ? "▲ HIDE SUMMARY" : "▼ SHOW SUMMARY"}
                  </button>
                  {expandedMarkdown === f.feature_id && (
                    <pre className="mt-2 text-xs font-mono text-lcars-muted whitespace-pre-wrap break-words leading-relaxed">
                      {f.markdown_content}
                    </pre>
                  )}
                </div>
              )}
```

- [ ] **Step 5: Build to verify no TypeScript errors**

```bash
cd M:/bridgecrew/dashboard/frontend
npm run build
```

Expected output: build succeeds, no type errors.

- [ ] **Step 6: Commit**

```bash
cd M:/bridgecrew
git add dashboard/frontend/src/pages/ProjectDetail.tsx
git commit -m "feat(frontend): add per-model cost breakdown and collapsible markdown panel to feature cards"
```
