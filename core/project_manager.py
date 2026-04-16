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

            # Sync features from local feature-mcp JSON store → dashboard
            if state.get("bridgecrew_project_id"):
                feature_results = self._sync_dashboard_features(name, state["bridgecrew_project_id"], project_dir)
                if feature_results:
                    results[name] = results.get(name, "exists") + f" ({feature_results})"

        # Check for removed projects
        for name in list(self._projects.keys()):
            if name not in discovered:
                project = self._projects.pop(name)
                if project.thread_id and project.thread_id in self._thread_to_project:
                    del self._thread_to_project[project.thread_id]
                self._config = remove_project_from_config(self._config, name)
                results[name] = "removed (directory missing)"
                log.info("Removed project %s from tracking — directory not found", name)

        save_config(self._config)
        return results

    def _sync_dashboard_features(self, project_name: str, project_id: str, project_dir: Path) -> str:
        """
        Read feature JSON files from disk and ensure each is represented in the dashboard.
        Creates missing features and updates status for completed ones.
        Returns a short summary string (e.g. "2 created, 1 updated").
        """
        import json as _json
        from core.bridgecrew_client import (
            get_features_for_project as _get_features,
            report_feature_started as _start,
            report_feature_completed as _complete,
        )

        features_dir = project_dir / ".claude" / "features"
        if not features_dir.exists():
            return ""

        local_features: list[dict] = []
        for p in sorted(features_dir.glob("*.json")):
            try:
                data = _json.loads(p.read_text(encoding="utf-8"))
                if data:
                    local_features.append(data)
            except Exception:
                continue

        if not local_features:
            return ""

        try:
            dashboard_features = _get_features(project_id)
        except Exception as exc:
            log.warning("_sync_dashboard_features: failed to fetch dashboard features for %s: %s", project_name, exc)
            return ""

        # Index dashboard features by name (lowered) for quick lookup
        dash_by_name: dict[str, dict] = {f.get("name", "").lower(): f for f in dashboard_features}

        created = updated = 0
        for feat in local_features:
            feat_name: str = feat.get("name", "")
            feat_status: str = feat.get("status", "active")
            if not feat_name:
                continue

            dash_feat = dash_by_name.get(feat_name.lower())

            if dash_feat is None:
                # Feature not in dashboard — create it
                session_id = ""
                for sess in feat.get("sessions", []):
                    if sess.get("session_id"):
                        session_id = sess["session_id"]
                        break
                composite_id = f"{project_name}:{feat_name}"
                new_id = _start(
                    project_id=project_id,
                    feature_name=feat_name,
                    session_id=session_id,
                    feature_id=composite_id,
                )
                if new_id and feat_status == "completed":
                    _complete(
                        feature_id=new_id,
                        summary=feat.get("summary", ""),
                        total_cost_usd=feat.get("total_cost_usd", 0.0),
                        total_input_tokens=feat.get("total_input_tokens", 0),
                        total_output_tokens=feat.get("total_output_tokens", 0),
                    )
                    updated += 1
                elif new_id:
                    created += 1
                log.info("_sync_dashboard_features: created feature %s/%s", project_name, feat_name)
            elif feat_status == "completed" and dash_feat.get("status") != "completed":
                # Feature exists but dashboard doesn't know it completed yet
                dash_id = dash_feat.get("feature_id") or dash_feat.get("_id") or dash_feat.get("id", "")
                if dash_id:
                    _complete(
                        feature_id=dash_id,
                        summary=feat.get("summary", ""),
                        total_cost_usd=feat.get("total_cost_usd", 0.0),
                        total_input_tokens=feat.get("total_input_tokens", 0),
                        total_output_tokens=feat.get("total_output_tokens", 0),
                    )
                    updated += 1
                    log.info("_sync_dashboard_features: marked completed %s/%s", project_name, feat_name)

        parts = []
        if created:
            parts.append(f"{created} feature{'s' if created != 1 else ''} created")
        if updated:
            parts.append(f"{updated} feature{'s' if updated != 1 else ''} updated")
        return ", ".join(parts)

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
