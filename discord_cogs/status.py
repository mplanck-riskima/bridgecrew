import asyncio
import os
import time

import httpx
import discord
from discord import app_commands
from discord.ext import commands

from discord_cogs import captains_only
from core.usage_tracker import get_usage_summary, get_rate_limits, RateLimits, fmt_tokens, fmt_time_until

_models_cache: list[tuple[str, str]] = []  # (id, display_name)
_models_cache_ts: float = 0.0
_MODELS_TTL = 3600.0  # 1 hour

_FALLBACK_MODELS: list[tuple[str, str]] = [
    ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
    ("claude-opus-5-5", "Claude Opus 5.5"),
    ("claude-haiku-5-5", "Claude Haiku 5.5"),
    ("claude-fable-5-1", "Claude Fable 5.1"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
]


async def _fetch_models() -> list[tuple[str, str]]:
    global _models_cache, _models_cache_ts
    now = time.monotonic()
    if _models_cache and now - _models_cache_ts < _MODELS_TTL:
        return _models_cache
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return _models_cache
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            _models_cache = [(m["id"], m.get("display_name", m["id"])) for m in data]
            _models_cache_ts = now
    except Exception:
        pass  # return stale cache on error
    return _models_cache or _FALLBACK_MODELS


def _pct_str(pct: float | None) -> str:
    if pct is None:
        return ""
    return f" ({pct:.0f}%)"


def _build_usage_lines(usage, rl: RateLimits) -> list[str]:
    """Return Claude Usage lines with real quota % from rate limits."""
    lines = ["**Claude Usage:**"]
    lines.append(
        f"- 5h: {fmt_tokens(usage.five_hour.output_tokens)} out / {fmt_tokens(usage.five_hour.input_tokens)} in"
        f" · ~${usage.five_hour.cost_usd:.2f}{_pct_str(rl.five_hour_pct)}"
        f" · {usage.five_hour.request_count} req"
    )
    lines.append(
        f"- Today: {fmt_tokens(usage.today.output_tokens)} out / {fmt_tokens(usage.today.input_tokens)} in"
        f" · ~${usage.today.cost_usd:.2f} · {usage.today.request_count} req"
        f" · resets {fmt_time_until(usage.daily_resets_at)}"
    )
    lines.append(
        f"- 7D: {fmt_tokens(usage.seven_day.output_tokens)} out / {fmt_tokens(usage.seven_day.input_tokens)} in"
        f" · ~${usage.seven_day.cost_usd:.2f}{_pct_str(rl.seven_day_pct)}"
        f" · {usage.seven_day.request_count} req"
    )
    return lines


def _fmt_elapsed(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m {s % 60}s"


class StatusCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        asyncio.create_task(_fetch_models())

    @app_commands.command(name="status", description="Show current status for this project")
    @captains_only()
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        channel = interaction.channel

        # If used in a thread, show project-specific status
        if isinstance(channel, discord.Thread):
            project = self.bot.project_manager.get_project_by_thread(channel.id)
            if not project:
                await interaction.followup.send("This thread isn't linked to a project.", ephemeral=True)
                return

            project_dir = self.bot.project_manager.get_project_dir(project)
            import json as _json
            from core.state import load_project_state as _lps_st
            _st_state = _lps_st(project_dir)
            _default_sid = _st_state.get("default_session_id")
            _features_dir = project_dir / ".claude" / "features"
            feature = None
            # Prefer the feature whose session matches default_session_id
            if _default_sid and _features_dir.exists():
                from models.feature import Feature as _Feature
                for _fp in sorted(_features_dir.glob("*.json")):
                    try:
                        _fd = _json.loads(_fp.read_text(encoding="utf-8"))
                        if _fd.get("status") == "active":
                            for _s in _fd.get("sessions", []):
                                if _s.get("session_id") == _default_sid and _s.get("status") == "active":
                                    feature = _Feature.from_dict(_fd["name"], _fd)
                                    break
                        if feature:
                            break
                    except Exception:
                        pass
            # Fallback: any active feature
            if feature is None and _features_dir.exists():
                from models.feature import Feature as _Feature
                for _fp in sorted(_features_dir.glob("*.json")):
                    try:
                        _fd = _json.loads(_fp.read_text(encoding="utf-8"))
                        if _fd.get("status") == "active":
                            feature = _Feature.from_dict(_fd["name"], _fd)
                            break
                    except Exception:
                        pass
            active_info = self.bot.claude_runner.get_active_info(channel.id)

            lines = [f"**Status for `{project.name}`:**"]
            if active_info:
                prompt_text, elapsed = active_info
                preview = prompt_text[:120] + ("…" if len(prompt_text) > 120 else "")
                lines.append(f"- Claude: **running** ({_fmt_elapsed(elapsed)})")
                lines.append(f"- Prompt: \"{preview}\"")
            else:
                lines.append("- Claude: idle")
            if feature:
                scope = f" (in `{feature.subdir}/`)" if feature.subdir else ""
                lines.append(f"- Active feature: `{feature.name}`{scope}")
                lines.append(f"- Session: `{feature.session_id[:8]}...`")
            else:
                lines.append("- No active feature")

            from core.state import load_project_state

            state = load_project_state(project_dir)

            # Show persona
            persona_name = state.get("persona_name")
            if persona_name:
                lines.append(f"- Persona: `{persona_name}`")

            # Show model (preferred takes priority, fall back to last-used)
            preferred_model = state.get("preferred_model")
            last_model = state.get("model")
            if preferred_model:
                lines.append(f"- Model: `{preferred_model}` (preferred)")
            elif last_model:
                lines.append(f"- Model: `{last_model}`")

            # Show last history entry
            history = state.get("history", [])
            if history:
                last = history[-1]
                lines.append(f"- Last prompt: \"{last['prompt_summary'][:80]}\" by {last['user']}")

            usage = await asyncio.to_thread(get_usage_summary)
            rl = get_rate_limits()
            lines.append("")
            lines.extend(_build_usage_lines(usage, rl))

            await interaction.followup.send("\n".join(lines))
        else:
            # Main channel — show overview
            pm = self.bot.project_manager
            projects = pm.projects
            if not projects:
                await interaction.followup.send("No projects. Run `/sync-projects` first.")
                return

            # Collect active and idle projects
            active_lines = []
            idle_lines = []
            for name, project in sorted(projects.items()):
                thread_id = project.thread_id
                is_busy = self.bot.claude_runner.is_busy(thread_id) if thread_id else False
                import json as _json
                _pdir = pm.get_project_dir(project)
                _fdir = _pdir / ".claude" / "features"
                feature = None
                if _fdir.exists():
                    for _fp in _fdir.glob("*.json"):
                        try:
                            _fd = _json.loads(_fp.read_text(encoding="utf-8"))
                            if _fd.get("status") == "active":
                                from models.feature import Feature as _Feature
                                feature = _Feature.from_dict(_fd["name"], _fd)
                                break
                        except Exception:
                            pass
                subdir_str = f" in `{feature.subdir}/`" if feature and feature.subdir else ""
                feat_str = f" | feature: `{feature.name}`{subdir_str}" if feature else ""
                thread_link = f" (<#{thread_id}>)" if thread_id else ""

                if is_busy:
                    active_info = self.bot.claude_runner.get_active_info(thread_id) if thread_id else None
                    if active_info:
                        prompt_text, elapsed = active_info
                        preview = prompt_text[:60] + ("…" if len(prompt_text) > 60 else "")
                        active_lines.append(f"- **{name}**{thread_link}{feat_str} ({_fmt_elapsed(elapsed)}): \"{preview}\"")
                    else:
                        active_lines.append(f"- **{name}**{thread_link}{feat_str}")
                else:
                    idle_lines.append(f"- {name}{feat_str}")

            lines = ["**Bot Status:**"]
            if self.bot._restart_requested:
                lines.append("\n⚠️ **Restart pending** — waiting for active processes to finish.")
            if active_lines:
                lines.append(f"\n🔄 **Active processes ({len(active_lines)}):**")
                lines.extend(active_lines)
            else:
                lines.append("\nNo active processes.")

            if idle_lines:
                lines.append(f"\n💤 **Idle ({len(idle_lines)}):**")
                lines.extend(idle_lines)

            usage = await asyncio.to_thread(get_usage_summary)
            rl = get_rate_limits()
            lines.append("")
            lines.extend(_build_usage_lines(usage, rl))

            await interaction.followup.send("\n".join(lines))

    @app_commands.command(name="restart-bot", description="Restart the bot process")
    @captains_only()
    async def restart_bot(self, interaction: discord.Interaction) -> None:
        prompt_cog = self.bot.cogs.get("ClaudePromptCog")
        active = []
        if prompt_cog and prompt_cog._workers:
            active = [t for t in prompt_cog._workers.values() if not t.done()]

        if active:
            await interaction.response.send_message(
                f"Restart queued — waiting for {len(active)} active process(es) to finish."
            )
        else:
            await interaction.response.send_message("Restarting... be right back!")
        await self.bot.request_restart(interaction.channel)

    @app_commands.command(name="force-restart", description="Restart immediately without waiting for active processes")
    @captains_only()
    async def force_restart(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Force restarting — killing all active processes!")
        self.bot._restart_requested = True
        await self.bot.close()

    @app_commands.command(name="cancel", description="Cancel the running Claude process for this project")
    @captains_only()
    async def cancel(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.Thread):
            await interaction.response.send_message("Use this in a project thread.", ephemeral=True)
            return

        if self.bot.claude_runner.cancel(channel.id):
            await interaction.response.send_message("Cancelled the running Claude process.")
        else:
            await interaction.response.send_message("No Claude process is running.", ephemeral=True)


    @captains_only()
    @app_commands.command(name="model", description="Set the Claude model for this project")
    @app_commands.describe(model="Model to use (start typing to search)")
    async def set_model(self, interaction: discord.Interaction, model: str) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.Thread):
            await interaction.response.send_message("Use this in a project thread.", ephemeral=True)
            return

        project = self.bot.project_manager.get_project_by_thread(channel.id)
        if not project:
            await interaction.response.send_message("This thread isn't linked to a project.", ephemeral=True)
            return

        from core.state import load_project_state, save_project_state

        project_dir = self.bot.project_manager.get_project_dir(project)
        state = load_project_state(project_dir)
        state["preferred_model"] = model
        save_project_state(project_dir, state)

        await interaction.response.send_message(f"Model set to `{model}` for `{project.name}`.")

    @set_model.autocomplete("model")
    async def model_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        models = await _fetch_models()
        needle = current.lower()
        matches = [
            (mid, dname)
            for mid, dname in models
            if not needle or needle in mid.lower() or needle in dname.lower()
        ]
        return [
            app_commands.Choice(name=f"{dname} ({mid})"[:100], value=mid)
            for mid, dname in matches[:25]
        ]

    @app_commands.command(name="reset-context", description="Reset the Claude session to start with a fresh context window")
    @captains_only()
    async def reset_context(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.Thread):
            await interaction.response.send_message("Use this in a project thread.", ephemeral=True)
            return

        project = self.bot.project_manager.get_project_by_thread(channel.id)
        if not project:
            await interaction.response.send_message("This thread isn't linked to a project.", ephemeral=True)
            return

        project_dir = self.bot.project_manager.get_project_dir(project)

        from core.state import load_project_state
        state = load_project_state(project_dir)
        old_session_id = state.get("default_session_id")

        # Determine the active feature name for the queue description
        _active_feat_name = None
        if old_session_id:
            from core.mcp_client import get_session_feature as _get_sf_reset
            _feat_dict = await _get_sf_reset(project_dir, old_session_id)
            if _feat_dict:
                _active_feat_name = _feat_dict.get("name")
        if not _active_feat_name:
            import json as _json
            _fdir = project_dir / ".claude" / "features"
            if _fdir.exists():
                for _fp in _fdir.glob("*.json"):
                    try:
                        _fd = _json.loads(_fp.read_text(encoding="utf-8"))
                        if _fd.get("status") == "active":
                            _active_feat_name = _fd.get("name")
                            break
                    except Exception:
                        pass

        label = f"feature **`{_active_feat_name}`**" if _active_feat_name else "project session"
        await interaction.response.send_message(f"Resetting context for {label}...", ephemeral=True)

        prompt_cog = self.bot.get_cog("ClaudePromptCog")
        if prompt_cog:
            queued = await prompt_cog.enqueue_reset_context(
                channel=channel,
                project_dir=project_dir,
                feature_name=_active_feat_name or "",
                old_session_id=old_session_id,
            )
            if queued:
                try:
                    await interaction.edit_original_response(
                        content=f"Queued: Resetting context for {label} — will run when current work completes.",
                    )
                except discord.HTTPException:
                    pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatusCog(bot))
