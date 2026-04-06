"""
/crew-member command — assign a Star Trek persona to a project thread.

Replaces the old /scotty-mode toggle. Personas are stored in the dashboard
MongoDB prompt_templates collection and fetched via the API.
"""
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from core.bridgecrew_client import list_prompts, assign_project_persona
from core.state import load_project_state, save_project_state
from discord_cogs import captains_only


# Series groupings for the dropdown UI
SERIES_ORDER = ["TOS", "TNG", "DS9", "VOY"]
SERIES_LABELS = {
    "TOS": "The Original Series",
    "TNG": "The Next Generation",
    "DS9": "Deep Space Nine",
    "VOY": "Voyager",
}


class CrewMemberView(discord.ui.View):
    """Shows up to 4 series dropdowns + a Clear button."""

    def __init__(self, prompts_by_series: dict[str, list[dict]], project_id: str, project_dir, bot):
        super().__init__(timeout=120)
        self.project_id = project_id
        self.project_dir = project_dir
        self.bot = bot

        for series in SERIES_ORDER:
            personas = prompts_by_series.get(series, [])
            if not personas:
                continue
            self.add_item(SeriesSelect(series, personas, project_id, project_dir, bot))

        # Also add any personas without a series tag
        other = prompts_by_series.get("other", [])
        if other:
            self.add_item(SeriesSelect("Other", other, project_id, project_dir, bot))

    @discord.ui.button(label="Clear persona", style=discord.ButtonStyle.secondary, row=4)
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: assign_project_persona(self.project_id, None))
        # Clear from project state
        state = load_project_state(self.project_dir)
        state.pop("persona_name", None)
        save_project_state(self.project_dir, state)
        await interaction.response.edit_message(content="Persona cleared. Using default voice.", view=None)


class SeriesSelect(discord.ui.Select):
    """Dropdown for one Star Trek series."""

    def __init__(self, series: str, personas: list[dict], project_id: str, project_dir, bot):
        label = SERIES_LABELS.get(series, series)
        options = []
        for p in personas[:25]:
            desc = p.get("description", "")[:100] or series
            options.append(discord.SelectOption(
                label=p.get("name", "Unknown"),
                value=p.get("_id", p.get("id", "")),
                description=desc,
            ))
        super().__init__(placeholder=f"{label} crew...", options=options, row=SERIES_ORDER.index(series) if series in SERIES_ORDER else 4)
        self.personas = {p.get("_id", p.get("id", "")): p for p in personas}
        self.project_id = project_id
        self.project_dir = project_dir
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        chosen_id = self.values[0]
        persona = self.personas.get(chosen_id, {})
        name = persona.get("name", "Unknown")

        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, lambda: assign_project_persona(self.project_id, chosen_id))

        if success:
            # Save persona name to project state for /status display
            state = load_project_state(self.project_dir)
            state["persona_name"] = name
            save_project_state(self.project_dir, state)
            await interaction.response.edit_message(content=f"Persona set to **{name}**.", view=None)
        else:
            await interaction.response.edit_message(content=f"Failed to assign persona. Is the dashboard running?", view=None)


class PersonasCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @captains_only()
    @app_commands.command(name="crew-member", description="Assign a Star Trek persona to this project")
    async def crew_member(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.Thread):
            await interaction.response.send_message("Use this in a project thread.", ephemeral=True)
            return

        project = self.bot.project_manager.get_project_by_thread(channel.id)
        if not project:
            await interaction.response.send_message("This thread isn't linked to a project.", ephemeral=True)
            return

        project_dir = self.bot.project_manager.get_project_dir(project)
        state = load_project_state(project_dir)
        project_id = state.get("bridgecrew_project_id", "")

        if not project_id:
            await interaction.response.send_message(
                "This project isn't registered in the dashboard yet. Run `/sync-projects` first.",
                ephemeral=True,
            )
            return

        # Fetch all personas from the API
        loop = asyncio.get_event_loop()
        prompts = await loop.run_in_executor(None, list_prompts)

        if not prompts:
            await interaction.response.send_message("No personas found. Is the dashboard running?", ephemeral=True)
            return

        # Group by series
        by_series: dict[str, list[dict]] = {}
        for p in prompts:
            series = p.get("series", "other") or "other"
            by_series.setdefault(series, []).append(p)

        current = state.get("persona_name")
        current_msg = f" (current: **{current}**)" if current else ""

        view = CrewMemberView(by_series, project_id, project_dir, self.bot)
        await interaction.response.send_message(
            f"Pick a crew member for **{project.name}**{current_msg}:",
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PersonasCog(bot))
