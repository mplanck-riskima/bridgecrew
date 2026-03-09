import asyncio
import logging
import os
import signal
import sys

import discord
from discord.ext import commands
from dotenv import load_dotenv

from core.claude_runner import ClaudeRunner
from core.feature_manager import FeatureManager
from core.project_manager import ProjectManager

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")
CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR")

if not DISCORD_TOKEN:
    sys.exit("DISCORD_TOKEN is required in .env")
if not GUILD_ID:
    sys.exit("DISCORD_GUILD_ID is required in .env")
if not CHANNEL_ID:
    sys.exit("DISCORD_CHANNEL_ID is required in .env")
if not WORKSPACE_DIR:
    sys.exit("WORKSPACE_DIR is required in .env")


intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = False


class ClaudeBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=intents)
        self.claude_runner = ClaudeRunner()
        self.feature_manager = FeatureManager()
        self.project_manager = ProjectManager(
            workspace_dir=WORKSPACE_DIR,
            guild_id=int(GUILD_ID),
            channel_id=int(CHANNEL_ID),
        )

    async def setup_hook(self) -> None:
        await self.load_extension("cogs.projects")
        await self.load_extension("cogs.features")
        await self.load_extension("cogs.claude_prompt")
        await self.load_extension("cogs.status")

        guild = discord.Object(id=int(GUILD_ID))
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        log.info("Slash commands synced to guild %s", GUILD_ID)

    async def on_ready(self) -> None:
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        log.info("Workspace: %s", WORKSPACE_DIR)

        # Auto-scan workspace on startup
        results = await self.project_manager.sync_projects(self)
        if results:
            for name, status in sorted(results.items()):
                log.info("Project %s: %s", name, status)
        else:
            log.info("No projects found in workspace")

    async def close(self) -> None:
        log.info("Shutting down — cancelling active Claude processes...")
        await self.claude_runner.cancel_all()
        await super().close()


bot = ClaudeBot()


def main() -> None:
    try:
        bot.run(DISCORD_TOKEN, log_handler=None)
    except KeyboardInterrupt:
        log.info("Interrupted")


if __name__ == "__main__":
    main()
