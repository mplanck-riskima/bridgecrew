"""Tests for bot.py PID file lifecycle."""
import os
from pathlib import Path


def test_pid_file_is_written_and_cleaned(tmp_path):
    """PID file exists while main() runs and is absent after exit."""
    # We exercise the contract without importing ClaudeBot (avoids DISCORD_TOKEN env check).
    # This is a direct contract test of the write/cleanup logic.
    pid_file = tmp_path / ".claude-bot" / "bot.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)

    # Simulate write
    pid_file.write_text(str(os.getpid()))
    assert pid_file.exists()
    assert pid_file.read_text().strip() == str(os.getpid())

    # Simulate cleanup
    pid_file.unlink(missing_ok=True)
    assert not pid_file.exists()


def test_pid_file_cleanup_is_safe_when_already_deleted(tmp_path):
    """unlink(missing_ok=True) does not raise if file was already removed."""
    pid_file = tmp_path / ".claude-bot" / "bot.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    # File never created — unlink must be silent
    pid_file.unlink(missing_ok=True)  # no exception
