# Feature Dashboard Enrichment Design

**Date:** 2026-04-15  
**Feature:** feature-stuff-on-pc  
**Status:** Approved

## Problem

Features initiated via the Discord bot are never registered in the dashboard MongoDB. The code to call `POST /api/features` on start and `PATCH /api/features/{id}` on complete exists in `bridgecrew_client.py` and `features.py` but is dead — the architecture shifted to feature-mcp and the dashboard wiring was never reconnected.

As a result:
- The dashboard shows no feature history
- Cost entries hit the dashboard but with no `feature_id`, so costs can't be joined to features
- There is no way to inspect feature content or per-model spend from the dashboard

## Goals

1. Wire feature registration so new features appear in the dashboard DB automatically
2. Store rendered markdown content in the dashboard when a feature is completed
3. Show per-model cost breakdown on each feature card
4. Show rendered markdown in a collapsible panel on completed feature cards

## Out of Scope

- Backfilling historical features (pre-fix features won't appear)
- Dashboard changes to the project header total cost
- Active feature markdown preview (only completed features show markdown)
- A separate costs tab or page per project

---

## Section 1: Feature Registration Fix

### Feature Start

**File:** `discord_cogs/features.py` → `run_feature_init_session()` (and the underlying `start_feature_session()` in `mcp_client.py`)

After `mcp_client.start_feature_session()` succeeds:
1. Call `bridgecrew_client.report_feature_started(project_id, name, description, session_id)` — this method already exists and calls `POST /api/features`
2. Store the returned dashboard ULID (`feature_id`) in the feature-mcp JSON as `bridgecrew_feature_id` by calling `feature_add_milestone` or a direct JSON patch — use `mcp_client` to write it back via a dedicated path

**Simplest approach:** `report_feature_started()` returns the dashboard `feature_id`. Write it to the feature-mcp JSON via a new `mcp_client` helper `set_bridgecrew_feature_id(project_dir, feature_name, bridgecrew_feature_id)` that PATCHes the feature-mcp REST endpoint with the id, or writes it directly to the JSON (feature-mcp owns the JSON, so a REST call is cleaner).

**Alternative:** Add a `bridgecrew_feature_id` field to the feature-mcp feature start/complete REST endpoints so it round-trips cleanly.

**Decision:** Use a new `PATCH /api/projects/{project_dir}/features/{feature_name}/set-bridgecrew-id` endpoint on feature-mcp, or simpler — store it in the feature-mcp JSON directly via a new `mcp_client.set_bridgecrew_feature_id()` helper that calls a new lightweight REST endpoint on feature-mcp.

### Feature Complete

**File:** `discord_cogs/features.py` → `run_feature_complete_session()`

After `mcp_client.complete_feature()` succeeds:
1. Read `bridgecrew_feature_id` from the feature-mcp JSON (via `feature_context` or a direct read)
2. Get the rendered markdown from `mcp_client.complete_feature()` return value (requires `feature_complete` in feature-mcp to return the rendered markdown string in its response — currently it writes to disk but doesn't return content)
3. Call `bridgecrew_client.report_feature_completed(bridgecrew_feature_id, summary, markdown_content, total_cost_usd)`

### Cost Reporting Fix

**File:** `discord_cogs/claude_prompt.py` → wherever `report_cost()` is called

Currently `feature_id` passed to `report_cost()` is empty or disconnected. After the fix:
- Read `bridgecrew_feature_id` from the active feature context (available via `mcp_client`)
- Pass it as `feature_id` to `report_cost()`

This is the key link that makes per-feature cost aggregation work.

---

## Section 2: Feature-MCP Changes

### Return Markdown from `feature_complete`

**File:** `feature-mcp/mcp_tools.py` → `feature_complete()`

Currently calls `_render_summary()` and writes to disk. Add the rendered string to the return payload:
```python
md_content = _render_summary(data, summary)
md_path.write_text(md_content, encoding="utf-8")
return {"status": "completed", ..., "markdown_content": md_content}
```

### Store `bridgecrew_feature_id`

**File:** `feature-mcp/rest_api.py` and `feature-mcp/feature_store.py`

Add a new REST endpoint:
```
PATCH /api/projects/{project_dir}/features/{feature_name}/bridgecrew-id
Body: { "bridgecrew_feature_id": "01JXXXXXXXXXXXXXXXXXXXXXXX" }
```

`feature_store.py` writes this field into the feature JSON. `feature_context()` returns it so callers can read it back.

---

## Section 3: Dashboard Backend Changes

### `PATCH /api/features/{feature_id}` — Add `markdown_content`

**File:** `dashboard/backend/app/routers/features.py`

Add to `FeatureUpdate`:
```python
markdown_content: str | None = None
```

MongoDB is schemaless — no migration needed. The field is stored and returned automatically.

### New Endpoint: Per-Feature Cost Breakdown

**File:** `dashboard/backend/app/routers/features.py`

```
GET /api/features/{feature_id}/costs/breakdown
Response:
{
  "by_model": {
    "claude-sonnet-4-6": {
      "cost_usd": 12.40,
      "input_tokens": 1200000,
      "output_tokens": 48000
    },
    "claude-opus-4-6": {
      "cost_usd": 3.20,
      "input_tokens": 80000,
      "output_tokens": 12000
    }
  }
}
```

Implementation: MongoDB aggregation on `cost_log_col` filtered by `feature_id`, grouped by `model`:
```python
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
```

Verify `feature_id` is indexed on `cost_log_col`; add index if missing.

---

## Section 4: `core/bridgecrew_client.py` Changes

### `report_feature_started()`

Already exists. Confirm it:
- POSTs to `POST /api/features` with `project_id`, `name`, `description`, `session_id`
- Returns the dashboard `feature_id` ULID

If it doesn't return the ULID from the response body, fix it to do so.

### `report_feature_completed()`

Add `markdown_content: str | None = None` parameter. Include in the PATCH body.

### `report_cost()`

Add `feature_id: str = ""` parameter (may already exist). Ensure callers pass `bridgecrew_feature_id`.

---

## Section 5: `core/mcp_client.py` Changes

### `complete_feature()`

Parse and return `markdown_content` from the feature-mcp REST response.

### `set_bridgecrew_feature_id()`

New helper:
```python
async def set_bridgecrew_feature_id(project_dir: str, feature_name: str, bridgecrew_feature_id: str) -> bool
```
Calls `PATCH /api/projects/{project_dir}/features/{feature_name}/bridgecrew-id`.

### `get_bridgecrew_feature_id()`

New helper that reads `bridgecrew_feature_id` from the feature context (via `feature_context()` response).

---

## Section 6: Frontend Changes

**File:** `dashboard/frontend/src/pages/ProjectDetail.tsx`

### Per-Model Cost Breakdown

- On feature card render, fetch `GET /api/features/{feature_id}/costs/breakdown`
- Replace the single `total_cost_usd` line with a model-by-model list:
  ```
  claude-sonnet-4-6   $12.40
  claude-opus-4-6      $3.20
  ──────────────────────────
  Total               $15.60
  ```
- Show for all features (active and completed) — if no cost data yet, show nothing
- Use a new `useFeatureCostBreakdown(feature_id)` hook or inline `useEffect`

### Markdown Panel (Completed Features Only)

- For features with `status === "completed"` and `markdown_content` set, render a collapsible panel below the cost breakdown
- Use `react-markdown` if not already in the project; otherwise use a simple `<pre>` block
- Check whether `react-markdown` is already a dependency before adding it

---

## Data Flow Summary

```
feature_start called
  → feature-mcp: creates JSON
  → bridgecrew_client.report_feature_started()
      → POST /api/features → returns dashboard ULID
  → mcp_client.set_bridgecrew_feature_id()
      → PATCH feature-mcp JSON with bridgecrew_feature_id

Claude response streamed
  → report_cost(feature_id=bridgecrew_feature_id, model=..., cost=...)
      → POST /api/costs → stored in cost_log_col with feature_id + model

feature_complete called
  → feature-mcp: renders markdown, writes .md, returns markdown_content
  → bridgecrew_client.report_feature_completed(markdown_content=...)
      → PATCH /api/features/{bridgecrew_feature_id}

Dashboard renders feature card
  → GET /api/features/{feature_id}/costs/breakdown → per-model list
  → markdown_content field → collapsible panel (completed only)
```

---

## Files Changed

| File | Change |
|------|--------|
| `feature-mcp/mcp_tools.py` | Return `markdown_content` from `feature_complete` |
| `feature-mcp/rest_api.py` | New `PATCH .../bridgecrew-id` endpoint |
| `feature-mcp/feature_store.py` | Store/return `bridgecrew_feature_id` field |
| `core/mcp_client.py` | Parse markdown from complete, add `set_bridgecrew_feature_id`, `get_bridgecrew_feature_id` |
| `core/bridgecrew_client.py` | Add `markdown_content` to `report_feature_completed`, ensure `report_feature_started` returns ULID |
| `discord_cogs/features.py` | Wire `report_feature_started` on start, `report_feature_completed` on complete |
| `discord_cogs/claude_prompt.py` | Pass `bridgecrew_feature_id` to `report_cost` |
| `dashboard/backend/app/routers/features.py` | Add `markdown_content` to `FeatureUpdate`; new cost breakdown endpoint |
| `dashboard/frontend/src/pages/ProjectDetail.tsx` | Per-model cost breakdown + markdown panel |
