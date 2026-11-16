# Resume Feature Autocomplete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded 25-item dropdown in `/resume-feature` with a Discord slash command autocomplete parameter that fuzzy-searches feature names as the user types.

**Architecture:** Add a fuzzy-scoring helper and an autocomplete handler to `discord_cogs/features.py`. The `/resume-feature` command gains a required `name: str` parameter with `autocomplete=True`. The command body calls `enqueue_feature_init` directly, bypassing `FeatureView` entirely.

**Tech Stack:** Python `difflib.SequenceMatcher` (stdlib), `discord.py` `app_commands.autocomplete`

**Spec:** Approved in conversation — autocomplete with prefix > substring > difflib scoring; empty input returns all features sorted by recency (active/suspended first).

## Global Constraints

- No new dependencies — fuzzy scoring uses `difflib` from stdlib only
- `FeatureSelect` / `FeatureView` classes are NOT removed — other commands still use them
- Autocomplete handler must resolve `project_dir` via `_resolve_project` on the cog instance
- Discord autocomplete returns at most 25 `app_commands.Choice` items

## Review Focus

- Out-of-thread invocation: autocomplete called outside a project thread should return empty list, not raise
- Feature list empty: command body should handle no features gracefully
- Exact name with spaces or special chars: scoring must not break on names like `"Bugs & Fixes"`
- Case sensitivity: search input should be case-insensitive
- Active/suspended features should sort above completed ones when input is empty

---

### Task 1: Fuzzy-scoring helper + autocomplete handler

**Files:**
- Modify: `discord_cogs/features.py` — add `_fuzzy_score()` helper and `resume_feature_autocomplete` handler; update `resume_feature` command signature and body

**Interfaces:**
- Produces: `_fuzzy_score(query: str, name: str) -> float` — returns 1.0 for prefix, 0.8 for substring, `SequenceMatcher` ratio otherwise (all case-insensitive)

- [ ] **Step 1: Add `_fuzzy_score` helper after `_list_feature_dicts`**

Add after line 27 (end of `_list_feature_dicts`):

```python
def _fuzzy_score(query: str, name: str) -> float:
    """Score a feature name against a search query. Higher = better match."""
    import difflib
    q, n = query.lower(), name.lower()
    if not q:
        return 1.0
    if n.startswith(q):
        return 1.0
    if q in n:
        return 0.8
    return difflib.SequenceMatcher(None, q, n).ratio()
```

- [ ] **Step 2: Update `resume_feature` command signature**

Change:
```python
@app_commands.command(name="resume-feature", description="Resume an existing or completed feature")
@captains_only()
async def resume_feature(self, interaction: discord.Interaction) -> None:
```

To:
```python
@app_commands.command(name="resume-feature", description="Resume an existing or completed feature")
@app_commands.describe(name="Feature name (type to search)")
@captains_only()
async def resume_feature(self, interaction: discord.Interaction, name: str) -> None:
```

- [ ] **Step 3: Replace the command body**

Replace the existing body (lines 907–919) with:

```python
    project, project_dir = self._resolve_project(interaction)
    if not project:
        await interaction.response.send_message("Use this command inside a project thread.", ephemeral=True)
        return

    _feat_dicts = _list_feature_dicts(project_dir)
    if not any(f.get("name") == name for f in _feat_dicts):
        await interaction.response.send_message(
            f"Feature **`{name}`** not found. Use `/list-features` to see available features.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        f"Resuming feature **`{name}`**...", ephemeral=True
    )
    prompt_cog = self.bot.cogs.get("ClaudePromptCog")
    if prompt_cog:
        queued = await prompt_cog.enqueue_feature_init(
            interaction.channel, project_dir, name, "resume"
        )
        if queued:
            try:
                await interaction.edit_original_response(
                    content=f"Queued: Resuming feature **`{name}`** — will run when current work completes.",
                )
            except discord.HTTPException:
                pass
```

- [ ] **Step 4: Add the autocomplete handler immediately after the command**

Add after the `resume_feature` method, before `complete_feature`:

```python
    @resume_feature.autocomplete("name")
    async def resume_feature_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        project, project_dir = self._resolve_project(interaction)
        if not project:
            return []
        _feat_dicts = _list_feature_dicts(project_dir)
        STATUS_ORDER = {"active": 0, "suspended": 1, "completed": 2}
        scored = sorted(
            _feat_dicts,
            key=lambda f: (
                STATUS_ORDER.get(f.get("status", "completed"), 3),
                -_fuzzy_score(current, f.get("name", "")),
            ),
        )
        MIN_SCORE = 0.3
        results = []
        for f in scored:
            name = f.get("name", "")
            score = _fuzzy_score(current, name)
            if current and score < MIN_SCORE:
                continue
            status = f.get("status", "?")
            label = f"{name} [{status}]"[:100]
            results.append(app_commands.Choice(name=label, value=name))
            if len(results) >= 25:
                break
        return results
```

- [ ] **Step 5: Verify manually (no automated test — this is a Discord interaction)**

Confirm in Discord:
- `/resume-feature` with no input shows features sorted active/suspended first
- Typing `rob` surfaces `robust-restart` at the top
- Typing a nonexistent name returns no matches
- Selecting a valid feature from autocomplete resumes it

- [ ] **Step 6: Commit**

```bash
git add discord_cogs/features.py
git commit -m "feat: replace resume-feature dropdown with fuzzy autocomplete param"
```

- [ ] **Step 7: Push**

```bash
git push
```
