import logging
from pathlib import Path

import discord

from core.state import (
    load_config,
    save_config,
    get_projects,
    set_project,
    remove_project as remove_project_from_config,
    load_project_state,
    save_project_state,
)
from models.project import Project

log = logging.getLogger(__name__)


class ProjectManager:
    def __init__(self, workspace_dir: str, guild_id: int, channel_id: int) -> None:
        self.workspace = Path(workspace_dir)
        self.guild_id = guild_id
        self.channel_id = channel_id
        self._config = load_config()
        self._projects = get_projects(self._config)
        # Reverse mapping: thread_id -> project name
        self._thread_to_project: dict[int, str] = {
            p.thread_id: name for name, p in self._projects.items() if p.thread_id
        }

    @property
    def projects(self) -> dict[str, Project]:
        return dict(self._projects)

    def get_project_by_thread(self, thread_id: int) -> Project | None:
        name = self._thread_to_project.get(thread_id)
        if name:
            return self._projects.get(name)
        return None

    def get_project_dir(self, project: Project) -> Path:
        return self.workspace / project.name

    def discover_projects(self) -> list[str]:
        """List subdirectory names in workspace that look like projects."""
        if not self.workspace.exists():
            log.warning("Workspace directory does not exist: %s", self.workspace)
            return []

        projects = []
        for entry in sorted(self.workspace.iterdir()):
            if not entry.is_dir():
                continue
            # Skip hidden directories
            if entry.name.startswith(".") or entry.name.startswith("_"):
                continue
            projects.append(entry.name)
        return projects

    async def sync_projects(self, bot: discord.Client) -> dict[str, str]:
        """Scan workspace and sync threads. Returns {project_name: status}."""
        guild = bot.get_guild(self.guild_id)
        if not guild:
            return {"error": "Guild not found"}

        channel = guild.get_channel(self.channel_id)
        log.info("Looking for channel ID %s, got: %s (type: %s)", self.channel_id, channel, type(channel).__name__ if channel else "None")
        if not channel or not isinstance(channel, discord.TextChannel):
            # Try fetching from API if not in cache
            try:
                channel = await guild.fetch_channel(self.channel_id)
                log.info("Fetched channel from API: %s (type: %s)", channel, type(channel).__name__)
            except Exception as e:
                log.error("Failed to fetch channel %s: %s", self.channel_id, e)
                return {"error": f"Channel not found or not a text channel (ID: {self.channel_id})"}

        discovered = self.discover_projects()
        results: dict[str, str] = {}

        for name in discovered:
            if name in self._projects and self._projects[name].thread_id:
                # Already tracked — verify thread still exists
                thread = guild.get_thread(self._projects[name].thread_id)
                if not thread:
                    # Cache miss — try fetching from API (handles archived threads)
                    try:
                        thread = await bot.fetch_channel(self._projects[name].thread_id)
                    except discord.NotFound:
                        thread = None
                    except discord.HTTPException as e:
                        log.warning("Failed to fetch thread %s for %s: %s", self._projects[name].thread_id, name, e)
                        thread = None

                if thread and isinstance(thread, discord.Thread):
                    # Unarchive if needed
                    if thread.archived:
                        try:
                            await thread.edit(archived=False)
                            results[name] = "unarchived"
                        except discord.HTTPException:
                            results[name] = "exists (archived)"
                    else:
                        results[name] = "exists"
                else:
                    # Thread was truly deleted — recreate
                    thread = await self._create_thread(channel, name)
                    if thread:
                        results[name] = "recreated"
                    else:
                        results[name] = "failed to recreate"
            else:
                # New project — create thread
                thread = await self._create_thread(channel, name)
                if thread:
                    results[name] = "created"
                else:
                    results[name] = "failed to create"

            # Ensure .claude-bot/state.json exists and dashboard project is linked
            project_dir = self.workspace / name
            state = load_project_state(project_dir)
            if not state.get("bridgecrew_project_id"):
                try:
                    from core.bridgecrew_client import get_projects as _get_projects, create_project as _create_project
                    dashboard_projects = _get_projects()
                    match = next((p for p in dashboard_projects if p.get("name") == name), None)
                    if match:
                        state["bridgecrew_project_id"] = match["project_id"]
                        log.info("Linked project %s to dashboard project %s", name, match["project_id"])
                    else:
                        project_id = _create_project(name)
                        if project_id:
                            state["bridgecrew_project_id"] = project_id
                            log.info("Created dashboard project for %s: %s", name, project_id)
                except Exception as exc:
                    log.warning("Failed to link dashboard project for %s: %s", name, exc)
            save_project_state(project_dir, state)

        # Check for removed projects
        for name in list(self._projects.keys()):
            if name not in discovered:
                results[name] = "directory missing"

        save_config(self._config)
        return results

    async def _create_thread(
        self, channel: discord.TextChannel, name: str
    ) -> discord.Thread | None:
        try:
            thread = await channel.create_thread(
                name=f"project: {name}",
                type=discord.ChannelType.public_thread,
            )
            project = Project(name=name, thread_id=thread.id)
            self._projects[name] = project
            self._thread_to_project[thread.id] = name
            self._config = set_project(self._config, project)
            await thread.send(f"**Project `{name}` linked.** Use @mention to send prompts to Claude.")
            return thread
        except discord.HTTPException as e:
            log.error("Failed to create thread for project %s: %s", name, e)
            return None
