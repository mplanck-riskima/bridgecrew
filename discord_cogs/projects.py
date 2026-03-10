import discord
from discord import app_commands
from discord.ext import commands


class ProjectsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="projects", description="List all discovered projects")
    async def projects(self, interaction: discord.Interaction) -> None:
        pm = self.bot.project_manager
        projects = pm.projects

        if not projects:
            await interaction.response.send_message("No projects found. Run `/sync-projects` to scan the workspace.")
            return

        lines = ["**Projects:**"]
        for name, project in sorted(projects.items()):
            thread_link = f"<#{project.thread_id}>" if project.thread_id else "no thread"
            # Get active feature
            project_dir = pm.get_project_dir(project)
            feature = self.bot.feature_manager.get_current_feature(project_dir)
            feature_str = f" | feature: `{feature.name}`" if feature else ""
            lines.append(f"- **{name}** → {thread_link}{feature_str}")

        await interaction.response.send_message("\n".join(lines))

    @app_commands.command(name="sync-projects", description="Scan workspace and sync project threads")
    async def sync_projects(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        pm = self.bot.project_manager
        results = await pm.sync_projects(self.bot)

        if "error" in results:
            await interaction.followup.send(f"**Error:** {results['error']}")
            return

        if not results:
            await interaction.followup.send("No projects found in workspace.")
            return

        lines = ["**Sync results:**"]
        for name, status in sorted(results.items()):
            lines.append(f"- `{name}`: {status}")

        await interaction.followup.send("\n".join(lines))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProjectsCog(bot))
