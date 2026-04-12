"""Shared fixtures for bot tests."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.bot.fakes.managers import (
    FakeProjectManager, FakeClaudeRunner, FakeVoiceNotifier,
)
from models.project import Project


def make_project(name: str = "test-project", thread_id: int = 999) -> Project:
    return Project(name=name, thread_id=thread_id)


def make_interaction(channel_id: int = 999, user_id: int = 1, guild_id: int = 1) -> MagicMock:
    """Create a mock discord.Interaction with common attributes."""
    interaction = MagicMock()
    interaction.channel_id = channel_id
    interaction.channel = MagicMock()
    interaction.channel.id = channel_id
    interaction.channel.__class__ = type("Thread", (), {})  # fakes isinstance check loosely
    interaction.response = AsyncMock()
    interaction.guild = MagicMock()
    interaction.guild.id = guild_id
    interaction.user = MagicMock()
    interaction.user.id = user_id
    return interaction


def make_thread(thread_id: int = 999) -> MagicMock:
    """Create a mock discord.Thread."""
    import discord
    thread = MagicMock(spec=discord.Thread)
    thread.id = thread_id
    return thread


@pytest.fixture
def fake_bot(tmp_path):
    """Create a fake bot with all managers replaced by fakes."""
    project = make_project()
    pm = FakeProjectManager(
        projects={999: project},
        workspace=tmp_path,
    )
    # Ensure project dir exists
    (tmp_path / project.name).mkdir(exist_ok=True)

    bot = MagicMock()
    bot.project_manager = pm
    bot.claude_runner = FakeClaudeRunner()
    bot.voice_notifier = FakeVoiceNotifier()
    bot.user = MagicMock()
    bot.user.id = 12345
    bot.cogs = {}
    bot._restart_requested = False
    bot.is_self_project = MagicMock(return_value=False)

    return bot, project, tmp_path
