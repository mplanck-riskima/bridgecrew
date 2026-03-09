import discord
from discord import app_commands
from discord.ext import commands


class FeaturesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

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

    @app_commands.command(name="start-feature", description="Start a new feature with a fresh Claude session")
    @app_commands.describe(name="Feature name (descriptive, e.g. 'add-auth-system')")
    async def start_feature(self, interaction: discord.Interaction, name: str) -> None:
        project, project_dir = self._resolve_project(interaction)
        if not project:
            await interaction.response.send_message("Use this command inside a project thread.", ephemeral=True)
            return

        feature = self.bot.feature_manager.start_feature(project_dir, name)
        await interaction.response.send_message(
            f"Feature **`{feature.name}`** started with fresh Claude session.\n"
            f"Session ID: `{feature.session_id[:8]}...`"
        )

    @app_commands.command(name="switch-feature", description="Switch to an existing feature")
    @app_commands.describe(name="Feature name to switch to")
    async def switch_feature(self, interaction: discord.Interaction, name: str) -> None:
        project, project_dir = self._resolve_project(interaction)
        if not project:
            await interaction.response.send_message("Use this command inside a project thread.", ephemeral=True)
            return

        feature = self.bot.feature_manager.switch_feature(project_dir, name)
        if not feature:
            available = self.bot.feature_manager.list_features(project_dir)
            names = ", ".join(f"`{f.name}`" for f in available) or "none"
            await interaction.response.send_message(
                f"Feature `{name}` not found. Available: {names}",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Switched to feature **`{feature.name}`**.\n"
            f"Session ID: `{feature.session_id[:8]}...`"
        )

    @app_commands.command(name="list-features", description="List all features for this project")
    async def list_features(self, interaction: discord.Interaction) -> None:
        project, project_dir = self._resolve_project(interaction)
        if not project:
            await interaction.response.send_message("Use this command inside a project thread.", ephemeral=True)
            return

        features = self.bot.feature_manager.list_features(project_dir)
        current = self.bot.feature_manager.get_current_feature(project_dir)

        if not features:
            await interaction.response.send_message("No features yet. Use `/start-feature` to create one.")
            return

        lines = [f"**Features for `{project.name}`:**"]
        for f in features:
            marker = " ← active" if current and f.name == current.name else ""
            lines.append(f"- `{f.name}` [{f.status}]{marker}")

        await interaction.response.send_message("\n".join(lines))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FeaturesCog(bot))
