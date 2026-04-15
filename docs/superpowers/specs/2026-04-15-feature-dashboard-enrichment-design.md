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

## ID Scheme

Features are identified by the same composite key everywhere — no ULIDs, no cross-system mapping tables:

```
feature_id = "{project_name}/{feature_name}"
```

`project_name` is the Discord bot's project name (e.g. `bridgecrew`). `feature_name` is the feature-mcp feature name (e.g. `feature-stuff-on-pc`). This key is unique by definition: project names are unique, and feature names are unique within a project.

The dashboard `POST /api/features` endpoint accepts a caller-supplied `feature_id` using this format instead of generating a ULID. The dashboard enforces uniqueness via a MongoDB unique index on `feature_id`.

Cost entries written to `cost_log_col` use the same composite key as `feature_id`, constructed at the call site from the active project name + feature name — no round-trip to retrieve a server-generated ID.

---

## Section 1: Feature Registration Fix

### Feature Start

**File:** `discord_cogs/features.py` → `run_feature_init_session()`

After `mcp_client.start_feature_session()` succeeds:
1. Construct `feature_id = f"{project_name}/{feature_name}"`
2. Call `bridgecrew_client.report_feature_started(feature_id, project_id, name, description, session_id)` — POSTs to `POST /api/features` with the caller-supplied `feature_id`

No ID storage or round-trip needed. The caller already knows the composite key.

### Feature Complete

**File:** `discord_cogs/features.py` → `run_feature_complete_session()`

After `mcp_client.complete_feature()` succeeds:
1. Construct `feature_id = f"{project_name}/{feature_name}"`
2. Get `markdown_content` from the `mcp_client.complete_feature()` return value (see Section 2)
3. Call `bridgecrew_client.report_feature_completed(feature_id, summary, markdown_content, total_cost_usd)`

### Cost Reporting Fix

**File:** `discord_cogs/claude_prompt.py` → wherever `report_cost()` is called

Currently `feature_id` passed to `report_cost()` is empty or disconnected. After the fix:
- Construct `feature_id = f"{project_name}/{feature_name}"` from the active project + feature context
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

**File:** `feature-mcp/rest_api.py` — the REST endpoint that wraps `feature_complete` must pass `markdown_content` through in its JSON response body so `mcp_client.complete_feature()` can read it.

No other changes to feature-mcp. The `bridgecrew_feature_id` field and the `PATCH .../bridgecrew-id` endpoint are not needed.

---

## Section 3: Dashboard Backend Changes

### `POST /api/features` — Accept Caller-Supplied `feature_id`

**File:** `dashboard/backend/app/routers/features.py`

Change `FeatureCreate` to accept an optional `feature_id`:
```python
class FeatureCreate(BaseModel):
    feature_id: str = ""   # if provided, use as-is; if empty, generate ULID (backwards compat)
    project_id: str
    name: str
    description: str = ""
    session_id: str = ""
    prompt_template_id: str = ""
    subdir: str = ""
```

When `feature_id` is provided (e.g. `"bridgecrew/feature-stuff-on-pc"`), use it directly. Add a unique index on `feature_id` if not already present.

### `PATCH /api/features/{feature_id}` — Add `markdown_content`

Add to `FeatureUpdate`:
```python
markdown_content: str | None = None
```

MongoDB is schemaless — no migration needed. The field is stored and returned automatically.

The `{feature_id}` path parameter in existing routes already works as a string — URL-encoding handles the `/` in composite keys (e.g. `bridgecrew%2Ffeature-stuff-on-pc`).

### New Endpoint: Per-Feature Cost Breakdown

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

Update signature to accept `feature_id` as the first argument (caller-supplied composite key). Include it in the `POST /api/features` body. Remove any logic that reads/returns a server-generated ULID.

### `report_feature_completed()`

Add `markdown_content: str | None = None` parameter. Include in the PATCH body. The `feature_id` argument is the composite key — no lookup needed.

### `report_cost()`

Confirm `feature_id: str = ""` parameter exists (may already). Callers pass the composite key constructed from active project name + feature name.

---

## Section 5: `core/mcp_client.py` Changes

### `complete_feature()`

Parse and return `markdown_content` from the feature-mcp REST response.

No other mcp_client changes needed — the `set_bridgecrew_feature_id` / `get_bridgecrew_feature_id` helpers from the previous design are not required.

---

## Section 6: Frontend Changes

**File:** `dashboard/frontend/src/pages/ProjectDetail.tsx`

### Per-Model Cost Breakdown

- On feature card render, fetch `GET /api/features/{feature_id}/costs/breakdown` (URL-encode the composite key)
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
  → feature_id = "{project_name}/{feature_name}"  ← constructed, not fetched
  → bridgecrew_client.report_feature_started(feature_id, ...)
      → POST /api/features with caller-supplied feature_id

Claude response streamed
  → feature_id = "{project_name}/{feature_name}"  ← constructed at call site
  → report_cost(feature_id=feature_id, model=..., cost=...)
      → POST /api/costs → stored in cost_log_col with feature_id + model

feature_complete called
  → feature-mcp: renders markdown, writes .md, returns markdown_content
  → feature_id = "{project_name}/{feature_name}"  ← constructed, not fetched
  → bridgecrew_client.report_feature_completed(feature_id, markdown_content=...)
      → PATCH /api/features/{feature_id}

Dashboard renders feature card
  → GET /api/features/{feature_id}/costs/breakdown → per-model list
  → markdown_content field → collapsible panel (completed only)
```

---

## Files Changed

| File | Change |
|------|--------|
| `feature-mcp/mcp_tools.py` | Return `markdown_content` from `feature_complete` |
| `feature-mcp/rest_api.py` | Pass `markdown_content` through in complete response |
| `core/mcp_client.py` | Parse `markdown_content` from complete response |
| `core/bridgecrew_client.py` | Accept caller-supplied `feature_id` in `report_feature_started`; add `markdown_content` to `report_feature_completed` |
| `discord_cogs/features.py` | Construct composite key; wire `report_feature_started` on start, `report_feature_completed` on complete |
| `discord_cogs/claude_prompt.py` | Construct composite key; pass as `feature_id` to `report_cost` |
| `dashboard/backend/app/routers/features.py` | Accept caller-supplied `feature_id` on POST; add `markdown_content` to `FeatureUpdate`; new cost breakdown endpoint |
| `dashboard/frontend/src/pages/ProjectDetail.tsx` | Per-model cost breakdown + markdown panel |
