import asyncio
import re
import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path

from core.bridgecrew_client import report_feature_completed, report_feature_started
from core.state import load_project_state, save_project_state
from discord_cogs import captains_only
from models.feature import Feature


def _list_feature_dicts(project_dir: Path) -> list[dict]:
    """Read all feature JSON files from .claude/features/. Returns list of raw dicts."""
    import json as _json
    features_dir = project_dir / ".claude" / "features"
    result = []
    if features_dir.exists():
        for fp in sorted(features_dir.glob("*.json")):
            try:
                data = _json.loads(fp.read_text(encoding="utf-8"))
                if data.get("name"):
                    result.append(data)
            except Exception:
                pass
    return result


class SubdirSelect(discord.ui.Select):
    """Dropdown for picking a subdirectory (or project root)."""

    def __init__(self, subdirs: list[str], feature_name: str, project_dir: Path, bot):
        options = [discord.SelectOption(label="Project root", value="__root__", description="Use the project root directory")]
        for d in subdirs[:24]:  # Discord max 25 options total
            options.append(discord.SelectOption(label=d, value=d))
        super().__init__(placeholder="Choose a directory...", options=options)
        self.feature_name = feature_name
        self.project_dir = project_dir
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        subdir = self.values[0] if self.values[0] != "__root__" else None

        scope = f"`{subdir}/`" if subdir else "project root"
        await interaction.response.edit_message(
            content=f"Starting feature **`{self.feature_name}`** in {scope}...",
            view=None,
        )

        prompt_cog = self.bot.cogs.get("ClaudePromptCog")
        if prompt_cog:
            asyncio.create_task(prompt_cog.run_feature_init_session(
                interaction.channel,
                self.project_dir,
                self.feature_name,
                "start",
                subdir=subdir,
            ))


class SubdirView(discord.ui.View):
    def __init__(self, subdirs: list[str], feature_name: str, project_dir: Path, bot):
        super().__init__(timeout=60)
        self.add_item(SubdirSelect(subdirs, feature_name, project_dir, bot))


class FeatureSelect(discord.ui.Select):
    """Dropdown for picking a feature to resume."""

    def __init__(self, features: list, project_dir: Path, bot):
        options = []
        for f in features[:25]:
            desc = f"{f.status}"
            if f.subdir:
                desc += f" · {f.subdir}/"
            options.append(discord.SelectOption(label=f.name, value=f.name, description=desc))
        super().__init__(placeholder="Choose a feature...", options=options)
        self.project_dir = project_dir
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        name = self.values[0]

        await interaction.response.edit_message(
            content=f"Resuming feature **`{name}`**...",
            view=None,
        )

        prompt_cog = self.bot.cogs.get("ClaudePromptCog")
        if prompt_cog:
            asyncio.create_task(prompt_cog.run_feature_init_session(
                interaction.channel,
                self.project_dir,
                name,
                "resume",
            ))


class FeatureView(discord.ui.View):
    def __init__(self, features: list, project_dir: Path, bot):
        super().__init__(timeout=60)
        self.add_item(FeatureSelect(features, project_dir, bot))


# ── Discard Feature UI ────────────────────────────────────────────────────────

class DiscardFeatureSelect(discord.ui.Select):
    """Dropdown for picking a feature to discard."""

    def __init__(self, features: list, project_dir: Path, bot):
        options = []
        for f in features[:25]:
            desc = f"{f.status}"
            if f.subdir:
                desc += f" · {f.subdir}/"
            options.append(discord.SelectOption(label=f.name, value=f.name, description=desc))
        super().__init__(placeholder="Choose a feature to discard...", options=options)
        self.project_dir = project_dir
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        name = self.values[0]
        view = DiscardConfirmView(name, self.project_dir, self.bot)
        await interaction.response.edit_message(
            content=f"**Discard `{name}`?** This removes feature tracking, archives the feature doc, and strips it from CLAUDE.md.",
            view=view,
        )


class DiscardConfirmView(discord.ui.View):
    def __init__(self, feature_name: str, project_dir: Path, bot):
        super().__init__(timeout=60)
        self.feature_name = feature_name
        self.project_dir = project_dir
        self.bot = bot

    @discord.ui.button(label="Discard", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        import json as _json
        import re as _re
        features_dir = self.project_dir / ".claude" / "features"

        # Use snake_case filename convention
        snake = self.feature_name.lower().replace("&", "and")
        snake = _re.sub(r"[-\s]+", "_", snake)
        snake = _re.sub(r"[^a-z0-9_]", "", snake)
        snake = _re.sub(r"_+", "_", snake).strip("_") or "unnamed"
        feat_path = features_dir / f"{snake}.json"

        feat_data = None
        if feat_path.exists():
            try:
                feat_data = _json.loads(feat_path.read_text(encoding="utf-8"))
                feat_path.unlink()
            except Exception:
                pass

        if not feat_data:
            await interaction.response.edit_message(content=f"Feature `{self.feature_name}` not found.", view=None)
            return

        subdir = feat_data.get("subdir")
        results = []

        # Archive feature doc
        archived = _archive_feature_doc(self.project_dir, self.feature_name, subdir)
        if archived:
            results.append(f"Archived `{archived}`")

        # Remove from CLAUDE.md
        removed = _remove_feature_from_claude_md(self.project_dir, self.feature_name)
        if removed:
            results.append("Removed from CLAUDE.md")

        results.append("Removed from feature tracking")

        # Clear the active feature name from project state if it matches the discarded feature
        from core.state import load_project_state as _lps_d, save_project_state as _sps_d
        _dstate = _lps_d(self.project_dir)
        if _dstate.get("active_feature_name") == self.feature_name:
            _dstate.pop("active_feature_name", None)
            _dstate.pop("pending_feature_op", None)
            _sps_d(self.project_dir, _dstate)

        await interaction.response.edit_message(
            content=f"**Discarded `{self.feature_name}`.**\n" + "\n".join(f"- {r}" for r in results),
            view=None,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Discard cancelled.", view=None)


def _archive_feature_doc(project_dir: Path, feature_name: str, subdir: str | None = None) -> str | None:
    """Move features/{name}.md to features/_archived/{name}.md. Returns archived path or None."""
    base = project_dir / subdir if subdir else project_dir
    doc_path = base / "features" / f"{feature_name}.md"
    if not doc_path.exists():
        return None
    archive_dir = base / "features" / "_archived"
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / f"{feature_name}.md"
    doc_path.rename(dest)
    return str(dest.relative_to(project_dir))


def _remove_feature_from_claude_md(project_dir: Path, feature_name: str) -> bool:
    """Strip the feature's bullet point from ## Features in CLAUDE.md."""
    claude_md = project_dir / "CLAUDE.md"
    if not claude_md.exists():
        return False
    content = claude_md.read_text(encoding="utf-8")
    # Match a bullet line that starts with the feature name (case-insensitive)
    pattern = re.compile(
        rf"^- \*\*{re.escape(feature_name)}\*\*.*$\n?",
        re.MULTILINE | re.IGNORECASE,
    )
    new_content, count = pattern.subn("", content)
    if count > 0:
        claude_md.write_text(new_content, encoding="utf-8")
        return True
    return False


class DiscardFeatureView(discord.ui.View):
    def __init__(self, features: list, project_dir: Path, bot):
        super().__init__(timeout=60)
        self.add_item(DiscardFeatureSelect(features, project_dir, bot))


# ── Resume CLI Session UI ─────────────────────────────────────────────────────

class SessionSelect(discord.ui.Select):
    """Step 1: Pick a CLI session to resume."""

    def __init__(self, sessions: list, project_dir: Path, bot):
        options = []
        for s in sessions[:25]:
            ts = s.timestamp.strftime("%m/%d %H:%M")
            label = f"{ts} — {s.first_message[:60]}"
            feat_tag = f" [{s.feature}]" if s.feature else ""
            desc = f"{s.session_id[:12]}...{feat_tag}"
            options.append(discord.SelectOption(label=label, value=s.session_id, description=desc))
        super().__init__(placeholder="Pick a session...", options=options)
        self.sessions = {s.session_id: s for s in sessions}
        self.project_dir = project_dir
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        session_id = self.values[0]
        session_info = self.sessions.get(session_id)

        # Step 2: Pick or create a feature to associate with
        _feat_dicts = _list_feature_dicts(self.project_dir)
        features = [Feature.from_dict(f["name"], f) for f in _feat_dicts]
        view = FeatureForSessionView(features, session_id, self.project_dir, self.bot)
        preview = session_info.first_message[:80] if session_info else session_id[:12]
        await interaction.response.edit_message(
            content=f"Session `{session_id[:12]}...` selected ({preview})\nPick a feature to associate it with, or create a new one:",
            view=view,
        )


class SessionSelectView(discord.ui.View):
    def __init__(self, sessions: list, project_dir: Path, bot):
        super().__init__(timeout=120)
        self.add_item(SessionSelect(sessions, project_dir, bot))


class FeatureForSessionSelect(discord.ui.Select):
    """Step 2: Pick an existing feature to wire the CLI session into."""

    def __init__(self, features: list, cli_session_id: str, project_dir: Path, bot):
        options = []
        for f in features[:24]:
            desc = f.status
            if f.subdir:
                desc += f" · {f.subdir}/"
            options.append(discord.SelectOption(label=f.name, value=f.name, description=desc))
        options.append(discord.SelectOption(label="+ New feature...", value="__new__", description="Create a new feature"))
        super().__init__(placeholder="Choose a feature...", options=options)
        self.cli_session_id = cli_session_id
        self.project_dir = project_dir
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]
        if choice == "__new__":
            modal = NewFeatureModal(self.cli_session_id, self.project_dir, self.bot)
            await interaction.response.send_modal(modal)
            return

        # Check feature exists
        _feat_dicts = _list_feature_dicts(self.project_dir)
        if not any(f.get("name") == choice for f in _feat_dicts):
            await interaction.response.edit_message(content=f"Feature `{choice}` not found.", view=None)
            return

        await interaction.response.edit_message(
            content=f"Resuming **`{choice}`** in session `{self.cli_session_id[:12]}...`...",
            view=None,
        )

        prompt_cog = self.bot.cogs.get("ClaudePromptCog")
        if prompt_cog:
            asyncio.create_task(prompt_cog.run_feature_init_session(
                interaction.channel,
                self.project_dir,
                choice,
                "resume",
                session_id=self.cli_session_id,
            ))


class FeatureForSessionView(discord.ui.View):
    def __init__(self, features: list, cli_session_id: str, project_dir: Path, bot):
        super().__init__(timeout=120)
        self.add_item(FeatureForSessionSelect(features, cli_session_id, project_dir, bot))


class NewFeatureModal(discord.ui.Modal, title="New Feature"):
    feature_name = discord.ui.TextInput(label="Feature name", placeholder="e.g. add-auth-system", max_length=100)

    def __init__(self, cli_session_id: str, project_dir: Path, bot):
        super().__init__()
        self.cli_session_id = cli_session_id
        self.project_dir = project_dir
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        name = self.feature_name.value.strip()
        if not name:
            await interaction.response.send_message("Feature name cannot be empty.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"Starting **`{name}`** in session `{self.cli_session_id[:12]}...`...",
            ephemeral=True,
        )

        prompt_cog = self.bot.cogs.get("ClaudePromptCog")
        if prompt_cog:
            asyncio.create_task(prompt_cog.run_feature_init_session(
                interaction.channel,
                self.project_dir,
                name,
                "start",
                session_id=self.cli_session_id,
            ))


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
        count = await _abandon(self.project_dir, self.feature_name)
        if count is not None:
            session_word = "session" if count == 1 else "sessions"
            await interaction.response.edit_message(
                content=f"Abandoned {count} active {session_word} for **`{self.feature_name}`**. You can now resume it cleanly.",
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


# ── Cog ───────────────────────────────────────────────────────────────────────

class FeaturesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _handle_auto_completed(self, channel, project_dir: Path, feature) -> None:
        """Handle cleanup for auto-completed features: API report + feature summary."""
        asyncio.create_task(self._report_feature_completed(project_dir, feature))
        prompt_cog = self.bot.cogs.get("ClaudePromptCog")
        if prompt_cog:
            # Look up project from thread
            project = None
            if isinstance(channel, discord.Thread):
                project = self.bot.project_manager.get_project_by_thread(channel.id)
            if project:
                asyncio.create_task(
                    prompt_cog.run_feature_summary_prompt(channel, project, feature)
                )

    async def _report_feature_started(self, project_dir: Path, feature) -> None:
        """Report feature start to BridgeCrew API and persist the returned feature_id."""
        state = load_project_state(project_dir)
        bc_project_id = state.get("bridgecrew_project_id", "")
        if not bc_project_id:
            return
        loop = asyncio.get_event_loop()
        feature_id = await loop.run_in_executor(
            None,
            lambda: report_feature_started(
                project_id=bc_project_id,
                feature_name=feature.name,
                session_id=feature.session_id,
                subdir=feature.subdir or "",
            ),
        )
        if feature_id:
            import json as _json
            import re as _re
            import os
            _snake = feature.name.lower().replace("&", "and")
            _snake = _re.sub(r"[-\s]+", "_", _snake)
            _snake = _re.sub(r"[^a-z0-9_]", "", _snake)
            _snake = _re.sub(r"_+", "_", _snake).strip("_") or "unnamed"
            _fp = project_dir / ".claude" / "features" / f"{_snake}.json"
            if _fp.exists():
                try:
                    _fd = _json.loads(_fp.read_text(encoding="utf-8"))
                    _fd["bridgecrew_feature_id"] = feature_id
                    _tmp = _fp.with_suffix(".tmp")
                    _tmp.write_text(_json.dumps(_fd, indent=2), encoding="utf-8")
                    os.replace(_tmp, _fp)
                except Exception:
                    pass

    async def _report_feature_completed(self, project_dir: Path, feature) -> None:
        """Report feature completion to BridgeCrew API."""
        bc_feature_id = feature.bridgecrew_feature_id
        if not bc_feature_id:
            # Try loading from feature file
            import json as _json, re as _re
            _snake = feature.name.lower().replace("&", "and")
            _snake = _re.sub(r"[-\s]+", "_", _snake)
            _snake = _re.sub(r"[^a-z0-9_]", "", _snake)
            _snake = _re.sub(r"_+", "_", _snake).strip("_") or "unnamed"
            _fp = project_dir / ".claude" / "features" / f"{_snake}.json"
            fdata = None
            if _fp.exists():
                try:
                    fdata = _json.loads(_fp.read_text(encoding="utf-8"))
                except Exception:
                    pass
            if fdata:
                bc_feature_id = fdata.get("bridgecrew_feature_id", "")
        if not bc_feature_id:
            return
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: report_feature_completed(
                feature_id=bc_feature_id,
                total_cost_usd=feature.total_cost_usd,
                total_input_tokens=feature.total_input_tokens,
                total_output_tokens=feature.total_output_tokens,
            ),
        )

    def _resolve_project(self, interaction: discord.Interaction):
        """Resolve the project from the thread context."""
        channel = interaction.channel
        if not isinstance(channel, discord.Thread):
            return None, None
        project = self.bot.project_manager.get_project_by_thread(channel.id)
        if not project:
            return None, None
        project_dir = self.bot.project_manager.get_project_dir(project)
        return project, project_dir

    @staticmethod
    def _list_subdirs(project_dir: Path) -> list[str]:
        """List immediate subdirectories, excluding hidden and common non-project dirs."""
        exclude = {
            "node_modules", "__pycache__", "dist", "build", "bin", "obj",
            ".git", ".claude", ".claude-bot", ".venv", "venv", "env",
        }
        subdirs = []
        for p in sorted(project_dir.iterdir()):
            if p.is_dir() and not p.name.startswith(".") and p.name not in exclude:
                subdirs.append(p.name)
        return subdirs

    def _check_active_work(self, thread_id: int) -> bool:
        """Check if Claude is actively working in a thread."""
        prompt_cog = self.bot.cogs.get("ClaudePromptCog")
        return prompt_cog and prompt_cog.has_active_work(thread_id)

    @captains_only()
    @app_commands.command(name="start-feature", description="Start a new feature with a fresh Claude session")
    @app_commands.describe(name="Feature name (descriptive, e.g. 'add-auth-system')")
    async def start_feature(self, interaction: discord.Interaction, name: str) -> None:
        project, project_dir = self._resolve_project(interaction)
        if not project:
            await interaction.response.send_message("Use this command inside a project thread.", ephemeral=True)
            return
        if self._check_active_work(interaction.channel_id):
            await interaction.response.send_message(
                "Claude is actively working. Wait for the queue to clear before switching features, or use `/clear-work` first.",
                ephemeral=True,
            )
            return

        subdirs = self._list_subdirs(project_dir)
        if subdirs:
            view = SubdirView(subdirs, name, project_dir, self.bot)
            await interaction.response.send_message(
                f"Starting feature **`{name}`** — which directory should it be scoped to?",
                view=view,
                ephemeral=True,
            )
        else:
            # No subdirectories — start a Claude session immediately
            await interaction.response.send_message(
                f"Starting feature **`{name}`**...",
                ephemeral=True,
            )
            prompt_cog = self.bot.cogs.get("ClaudePromptCog")
            if prompt_cog:
                asyncio.create_task(prompt_cog.run_feature_init_session(
                    interaction.channel,
                    project_dir,
                    name,
                    "start",
                ))

    @app_commands.command(name="resume-feature", description="Resume an existing or completed feature")
    @captains_only()
    async def resume_feature(self, interaction: discord.Interaction) -> None:
        project, project_dir = self._resolve_project(interaction)
        if not project:
            await interaction.response.send_message("Use this command inside a project thread.", ephemeral=True)
            return
        if self._check_active_work(interaction.channel_id):
            await interaction.response.send_message(
                "Claude is actively working. Wait for the queue to clear before switching features, or use `/clear-work` first.",
                ephemeral=True,
            )
            return

        _feat_dicts = _list_feature_dicts(project_dir)
        features = [Feature.from_dict(f["name"], f) for f in _feat_dicts]
        if not features:
            await interaction.response.send_message("No features yet. Use `/start-feature` to create one.", ephemeral=True)
            return

        view = FeatureView(features, project_dir, self.bot)
        await interaction.response.send_message("Pick a feature to resume:", view=view, ephemeral=True)

    @captains_only()
    @app_commands.command(name="complete-feature", description="Mark a feature as completed")
    @app_commands.describe(name="Feature name to complete (defaults to current active feature)")
    async def complete_feature(self, interaction: discord.Interaction, name: str | None = None) -> None:
        project, project_dir = self._resolve_project(interaction)
        if not project:
            await interaction.response.send_message("Use this command inside a project thread.", ephemeral=True)
            return
        if self._check_active_work(interaction.channel_id):
            await interaction.response.send_message(
                "Claude is actively working. Wait for the queue to clear before completing features, or use `/clear-work` first.",
                ephemeral=True,
            )
            return

        state = load_project_state(project_dir)
        session_id = state.get("default_session_id")
        if not session_id:
            await interaction.response.send_message(
                "No active Claude session found for this thread. Start a feature first.",
                ephemeral=True,
            )
            return

        # Resolve feature name from MCP store if not explicitly provided
        if name:
            feature_name = name
        else:
            from core.mcp_client import get_session_feature as _get_sf
            feat_dict = await _get_sf(project_dir, session_id)
            if not feat_dict:
                await interaction.response.send_message(
                    "No active feature found for this session. Use `/start-feature` or `/resume-feature` first.",
                    ephemeral=True,
                )
                return
            feature_name = feat_dict["name"]

        await interaction.response.send_message(
            f"Completing **`{feature_name}`** — Claude will review the work, write the summary, and close out the feature.",
            ephemeral=True,
        )
        prompt_cog = self.bot.cogs.get("ClaudePromptCog")
        if prompt_cog:
            asyncio.create_task(prompt_cog.run_feature_complete_session(
                interaction.channel, project_dir, feature_name, session_id,
            ))

    @captains_only()
    @app_commands.command(name="resume-session", description="Resume a CLI session from this machine in Discord")
    async def resume_session(self, interaction: discord.Interaction) -> None:
        project, project_dir = self._resolve_project(interaction)
        if not project:
            await interaction.response.send_message("Use this command inside a project thread.", ephemeral=True)
            return

        sessions = self.bot.claude_runner.scan_cli_sessions(project_dir)
        if not sessions:
            await interaction.response.send_message(
                "No recent CLI sessions found for this project (checked last 24 hours).",
                ephemeral=True,
            )
            return

        # Annotate sessions with feature names if already linked
        _feat_dicts = _list_feature_dicts(project_dir)
        _session_to_feature = {}
        for fd in _feat_dicts:
            for sess in fd.get("sessions", []):
                sid = sess.get("session_id")
                if sid:
                    _session_to_feature[sid] = fd.get("name")
        for s in sessions:
            s.feature = _session_to_feature.get(s.session_id)

        view = SessionSelectView(sessions, project_dir, self.bot)
        await interaction.response.send_message(
            f"Found **{len(sessions)}** recent CLI session(s). Pick one to resume:",
            view=view,
            ephemeral=True,
        )

    @captains_only()
    @app_commands.command(name="discard-feature", description="Remove a feature from tracking and archive its docs")
    async def discard_feature(self, interaction: discord.Interaction) -> None:
        project, project_dir = self._resolve_project(interaction)
        if not project:
            await interaction.response.send_message("Use this command inside a project thread.", ephemeral=True)
            return

        _feat_dicts = _list_feature_dicts(project_dir)
        features = [Feature.from_dict(f["name"], f) for f in _feat_dicts]
        if not features:
            await interaction.response.send_message("No features to discard.", ephemeral=True)
            return

        view = DiscardFeatureView(features, project_dir, self.bot)
        await interaction.response.send_message("Pick a feature to discard:", view=view, ephemeral=True)

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

    @app_commands.command(name="list-features", description="List all features for this project")
    @captains_only()
    async def list_features(self, interaction: discord.Interaction) -> None:
        project, project_dir = self._resolve_project(interaction)
        if not project:
            await interaction.response.send_message("Use this command inside a project thread.", ephemeral=True)
            return

        _feat_dicts = _list_feature_dicts(project_dir)
        features = [Feature.from_dict(f["name"], f) for f in _feat_dicts]

        if not features:
            await interaction.response.send_message("No features yet. Use `/start-feature` to create one.")
            return

        lines = [f"**Features for `{project.name}`:**"]
        for f in features:
            marker = " <- active" if f.status == "active" else ""
            scope = f" (`{f.subdir}/`)" if f.subdir else ""
            lines.append(f"- `{f.name}` [{f.status}]{scope}{marker}")

        await interaction.response.send_message("\n".join(lines))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FeaturesCog(bot))
