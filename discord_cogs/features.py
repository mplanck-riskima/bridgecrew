import asyncio
import re
import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path

from core.bridgecrew_client import report_feature_completed, report_feature_started
from core.state import load_project_state, save_project_state, load_feature_index
from discord_cogs import captains_only


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

        # Auto-complete any currently active features
        cog = self.bot.cogs.get("FeaturesCog")
        auto_completed = self.bot.feature_manager.auto_complete_active_features(
            self.project_dir, exclude_name=self.feature_name
        )
        if cog and auto_completed:
            for completed_feat in auto_completed:
                asyncio.create_task(cog._handle_auto_completed(interaction.channel, self.project_dir, completed_feat))

        feature = self.bot.feature_manager.start_feature(self.project_dir, self.feature_name, subdir=subdir)
        scope = f"`{subdir}/`" if subdir else "project root"
        completed_msg = ""
        if auto_completed:
            names = ", ".join(f"`{f.name}`" for f in auto_completed)
            completed_msg = f"\nCompleted: {names}"
        await interaction.response.edit_message(
            content=(
                f"Feature **`{feature.name}`** started in {scope}.\n"
                f"Session ID: `{feature.session_id[:8]}...`{completed_msg}"
            ),
            view=None,
        )
        if cog:
            asyncio.create_task(cog._report_feature_started(self.project_dir, feature))


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

        # Auto-complete any currently active features (except the one being resumed)
        cog = self.bot.cogs.get("FeaturesCog")
        auto_completed = self.bot.feature_manager.auto_complete_active_features(
            self.project_dir, exclude_name=name
        )
        if cog and auto_completed:
            for completed_feat in auto_completed:
                asyncio.create_task(cog._handle_auto_completed(interaction.channel, self.project_dir, completed_feat))

        feature = self.bot.feature_manager.resume_feature(self.project_dir, name)
        if not feature:
            await interaction.response.edit_message(content=f"Feature `{name}` not found.", view=None)
            return
        scope = f" in `{feature.subdir}/`" if feature.subdir else ""
        completed_msg = ""
        if auto_completed:
            names = ", ".join(f"`{f.name}`" for f in auto_completed)
            completed_msg = f"\nCompleted: {names}"
        await interaction.response.edit_message(
            content=(
                f"Resumed feature **`{feature.name}`**{scope}.\n"
                f"Session ID: `{feature.session_id[:8]}...`{completed_msg}"
            ),
            view=None,
        )


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
        feat = self.bot.feature_manager.discard_feature(self.project_dir, self.feature_name)
        if not feat:
            await interaction.response.edit_message(content=f"Feature `{self.feature_name}` not found.", view=None)
            return

        results = []

        # Archive feature doc
        archived = _archive_feature_doc(self.project_dir, self.feature_name, feat.subdir)
        if archived:
            results.append(f"Archived `{archived}`")

        # Remove from CLAUDE.md
        removed = _remove_feature_from_claude_md(self.project_dir, self.feature_name)
        if removed:
            results.append("Removed from CLAUDE.md")

        results.append("Removed from feature tracking")

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
        features = self.bot.feature_manager.list_features(self.project_dir)
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
            # Ask for name via modal
            modal = NewFeatureModal(self.cli_session_id, self.project_dir, self.bot)
            await interaction.response.send_modal(modal)
            return

        # Wire the CLI session into the chosen feature
        feat = self.bot.feature_manager.register_cli_session(self.project_dir, self.cli_session_id, choice)
        if not feat:
            await interaction.response.edit_message(content=f"Feature `{choice}` not found.", view=None)
            return
        await interaction.response.edit_message(
            content=(
                f"Session `{self.cli_session_id[:12]}...` linked to **`{choice}`**.\n"
                f"Your next prompt will resume this CLI session."
            ),
            view=None,
        )


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

        # Start the feature, then register the CLI session
        self.bot.feature_manager.start_feature(self.project_dir, name)
        feat = self.bot.feature_manager.register_cli_session(self.project_dir, self.cli_session_id, name)

        await interaction.response.send_message(
            f"Created feature **`{name}`** and linked session `{self.cli_session_id[:12]}...`.\n"
            f"Your next prompt will resume this CLI session.",
            ephemeral=True,
        )


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
        bc_project_id = state.get("myvillage_project_id", "") or state.get("bridgecrew_project_id", "")
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
            from core.state import load_feature_file, save_feature_file
            fdata = load_feature_file(project_dir, feature.name)
            if fdata:
                fdata["bridgecrew_feature_id"] = feature_id
                fdata["name"] = feature.name
                save_feature_file(project_dir, feature.name, fdata)

    async def _report_feature_completed(self, project_dir: Path, feature) -> None:
        """Report feature completion to BridgeCrew API."""
        bc_feature_id = feature.bridgecrew_feature_id
        if not bc_feature_id:
            # Try loading from feature file
            from core.state import load_feature_file
            fdata = load_feature_file(project_dir, feature.name)
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
            # No subdirectories — start at project root directly
            # Auto-complete active features first
            auto_completed = self.bot.feature_manager.auto_complete_active_features(project_dir, exclude_name=name)
            for completed_feat in auto_completed:
                asyncio.create_task(self._handle_auto_completed(interaction.channel, project_dir, completed_feat))

            feature = self.bot.feature_manager.start_feature(project_dir, name)
            asyncio.create_task(self._report_feature_started(project_dir, feature))
            completed_msg = ""
            if auto_completed:
                names = ", ".join(f"`{f.name}`" for f in auto_completed)
                completed_msg = f"\nCompleted: {names}"
            await interaction.response.send_message(
                f"Feature **`{feature.name}`** started.\n"
                f"Session ID: `{feature.session_id[:8]}...`{completed_msg}"
            )

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

        features = self.bot.feature_manager.list_features(project_dir)
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

        from core.state import load_project_state
        session_id = load_project_state(project_dir).get("default_session_id")
        feature = self.bot.feature_manager.complete_feature(project_dir, name, session_id=session_id)
        if not feature:
            if name:
                await interaction.response.send_message(f"Feature `{name}` not found.", ephemeral=True)
            else:
                await interaction.response.send_message("No active feature to complete.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"Feature **`{feature.name}`** marked as completed. Generating feature summary..."
        )

        asyncio.create_task(self._report_feature_completed(project_dir, feature))

        prompt_cog = self.bot.cogs.get("ClaudePromptCog")
        if prompt_cog and project:
            asyncio.create_task(
                prompt_cog.run_feature_summary_prompt(interaction.channel, project, feature)
            )

        if interaction.guild:
            asyncio.create_task(self.bot.voice_notifier.voice_event(
                interaction.guild, "feature_complete",
                f"Feature {feature.name} is complete in {project.name}."
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
        index = load_feature_index(project_dir)
        for s in sessions:
            session_entry = index.get("sessions", {}).get(s.session_id)
            if session_entry:
                s.feature = session_entry.get("feature")

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

        features = self.bot.feature_manager.list_features(project_dir)
        if not features:
            await interaction.response.send_message("No features to discard.", ephemeral=True)
            return

        view = DiscardFeatureView(features, project_dir, self.bot)
        await interaction.response.send_message("Pick a feature to discard:", view=view, ephemeral=True)

    @app_commands.command(name="list-features", description="List all features for this project")
    @captains_only()
    async def list_features(self, interaction: discord.Interaction) -> None:
        project, project_dir = self._resolve_project(interaction)
        if not project:
            await interaction.response.send_message("Use this command inside a project thread.", ephemeral=True)
            return

        features = self.bot.feature_manager.list_features(project_dir)

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
