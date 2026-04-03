import discord
from discord import app_commands
from discord.ext import commands

from discord_cogs import captains_only
from core.usage_tracker import get_usage_summary, fmt_tokens, fmt_time_until


def _fmt_elapsed(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m {s % 60}s"


class StatusCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="status", description="Show current status for this project")
    @captains_only()
    async def status(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel

        # If used in a thread, show project-specific status
        if isinstance(channel, discord.Thread):
            project = self.bot.project_manager.get_project_by_thread(channel.id)
            if not project:
                await interaction.response.send_message("This thread isn't linked to a project.", ephemeral=True)
                return

            project_dir = self.bot.project_manager.get_project_dir(project)
            feature = self.bot.feature_manager.get_current_feature(project_dir)
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

            usage = get_usage_summary()
            lines.append("")
            lines.append("**Claude Usage:**")
            lines.append(
                f"- Today: {fmt_tokens(usage.today.output_tokens)} out / {fmt_tokens(usage.today.input_tokens)} in"
                f" · ~${usage.today.cost_usd:.2f} · {usage.today.request_count} req"
                f" · resets {fmt_time_until(usage.daily_resets_at)}"
            )
            lines.append(
                f"- This week: {fmt_tokens(usage.this_week.output_tokens)} out / {fmt_tokens(usage.this_week.input_tokens)} in"
                f" · ~${usage.this_week.cost_usd:.2f} · {usage.this_week.request_count} req"
                f" · resets {fmt_time_until(usage.weekly_resets_at)}"
            )

            await interaction.response.send_message("\n".join(lines))
        else:
            # Main channel — show overview
            pm = self.bot.project_manager
            projects = pm.projects
            if not projects:
                await interaction.response.send_message("No projects. Run `/sync-projects` first.")
                return

            # Collect active and idle projects
            active_lines = []
            idle_lines = []
            for name, project in sorted(projects.items()):
                thread_id = project.thread_id
                is_busy = self.bot.claude_runner.is_busy(thread_id) if thread_id else False
                feature = self.bot.feature_manager.get_current_feature(pm.get_project_dir(project))
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

            usage = get_usage_summary()
            lines.append("\n**Claude Usage:**")
            lines.append(
                f"- Today: {fmt_tokens(usage.today.output_tokens)} out / {fmt_tokens(usage.today.input_tokens)} in"
                f" · ~${usage.today.cost_usd:.2f} · {usage.today.request_count} req"
                f" · resets {fmt_time_until(usage.daily_resets_at)}"
            )
            lines.append(
                f"- This week: {fmt_tokens(usage.this_week.output_tokens)} out / {fmt_tokens(usage.this_week.input_tokens)} in"
                f" · ~${usage.this_week.cost_usd:.2f} · {usage.this_week.request_count} req"
                f" · resets {fmt_time_until(usage.weekly_resets_at)}"
            )

            await interaction.response.send_message("\n".join(lines))

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
    @app_commands.describe(model="Model to use")
    @app_commands.choices(model=[
        app_commands.Choice(name="Opus (most capable)", value="claude-opus-4-6"),
        app_commands.Choice(name="Sonnet (balanced)", value="claude-sonnet-4-6"),
        app_commands.Choice(name="Haiku (fastest)", value="claude-haiku-4-5-20251001"),
    ])
    async def set_model(self, interaction: discord.Interaction, model: app_commands.Choice[str]) -> None:
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
        state["preferred_model"] = model.value
        save_project_state(project_dir, state)

        await interaction.response.send_message(f"Model set to **{model.name}** (`{model.value}`) for `{project.name}`.")

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

        if self.bot.claude_runner.is_busy(channel.id):
            await interaction.response.send_message("Claude is currently running. Cancel it first with `/cancel`.", ephemeral=True)
            return

        project_dir = self.bot.project_manager.get_project_dir(project)
        feature = self.bot.feature_manager.get_current_feature(project_dir)

        from core.state import load_project_state, save_project_state, load_feature_index, save_feature_index, load_feature_file, save_feature_file

        if feature:
            # Null session to force a fresh context window; keep cumulative token counts
            feat_data = load_feature_file(project_dir, feature.name)
            if feat_data:
                feat_data["session_id"] = None
                feat_data["name"] = feature.name
                save_feature_file(project_dir, feature.name, feat_data)
            # Remove session from index
            index = load_feature_index(project_dir)
            state = load_project_state(project_dir)
            old_sid = state.get("default_session_id")
            if old_sid and old_sid in index.get("sessions", {}):
                del index["sessions"][old_sid]
                save_feature_index(project_dir, index)
            label = f"feature `{feature.name}`"
        else:
            state = load_project_state(project_dir)
            state["default_session_id"] = None
            state["session_usage"] = {
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_cost_usd": 0.0,
                "prompt_count": 0,
            }
            label = "project session"

        state["default_session_id"] = None
        save_project_state(project_dir, state)
        await interaction.response.send_message(f"Context reset for {label}. The next prompt will start a fresh Claude session.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatusCog(bot))
