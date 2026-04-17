# features-on-dashboard

**Started:** 2026-04-16  
**Completed:** 2026-04-16  
**Cost:** $7.0537

## Summary

Full feature lifecycle tracking in the monitoring dashboard — features are registered, enriched, and displayed end-to-end from the Discord bot through to the React UI, with backfill tooling for existing data.

**What was built:**

1. **Bot → Dashboard reporting** (`core/bridgecrew_client.py`, `discord_cogs/claude_prompt.py`): `report_feature_started` sends a feature record with a `project:feature` composite key on `/start-feature`; `report_feature_completed` patches it with summary, costs, and `markdown_content` on completion.

2. **Composite feature ID** throughout: `project_name:feature_name` replaces ULIDs as the public `feature_id`, consistent across cost reporting, start, and complete calls.

3. **Dashboard backend** (`routers/features.py`, `db.py`): unique index on `feature_id`, non-unique index on `cost_log.feature_id`; `markdown_content` field on `FeatureUpdate`; `GET /features/{id}/costs/breakdown` aggregation endpoint; graceful duplicate handling on create.

4. **Dashboard frontend** (`ProjectDetail.tsx`, `MarkdownContent.tsx`): per-model cost breakdown per feature card; all cards expandable (click to toggle); `react-markdown` + `remark-gfm` renders markdown with LCARS-styled headings, lists, code blocks, and links; "No summary recorded." fallback.

5. **Sync-projects backfill** (`core/project_manager.py`, `core/bridgecrew_client.py`): `/sync-projects` calls `_sync_dashboard_features` after linking each project — creates missing dashboard features from local feature-mcp JSON and marks completed ones. `get_features_for_project()` unwraps the paginated envelope correctly.

6. **Human-readable project URLs** (`Projects.tsx`, `Dashboard.tsx`, `ProjectDetail.tsx`, `routers/projects.py`): project URLs use `encodeURIComponent(name)` (`/projects/bridgecrew`); backend `_resolve_project()` tries project_id then name; `ProjectDetail` uses resolved `project.project_id` for activity/update API calls.

7. **Migration script** (`migrate_feature_ids.py`): Pass 1 renames ULID feature_ids to composite keys, cascading to cost_log. Pass 2 backfills `summary` and `markdown_content` from local `.md` files, extracting the `## Summary` section. Supports `--dry-run`, `--skip-id-migration`, `--skip-summary-backfill`. Ran against production: 33 IDs migrated, 24 features backfilled.

8. **UI cleanup**: removed delete-project and delete-feature buttons (Discord is source of truth); removed Costs tab from project detail; mobile header shows commit hash; removed unused `LcarsPanel` component that caused Railway build failure.

**Key design decisions:**
- `project:feature` composite key chosen so bot and CLI can construct the same ID independently without a DB round-trip.
- `_resolve_project()` tries ULID first so existing bookmarks remain functional.
- Feature cards are always expandable regardless of whether summary/markdown is present, to avoid silent non-interactivity.
