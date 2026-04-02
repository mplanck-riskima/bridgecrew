"""E2E security test fixtures.

Builds the system prompt exactly as the bot does, then runs
`claude -p --dangerously-skip-permissions --output-format stream-json`
from a temporary project directory.
"""
import json
import subprocess
import shutil
import pytest
from pathlib import Path

from core.system_prompt import NO_PERSONA, STATIC_SYSTEM_PROMPT


def _claude_available() -> bool:
    return shutil.which("claude") is not None


skip_no_claude = pytest.mark.skipif(
    not _claude_available(),
    reason="claude CLI not on PATH",
)


@pytest.fixture
def project_dir(tmp_path):
    """Create a temporary project directory with a test file."""
    (tmp_path / "hello.txt").write_text("Hello from the test project!")
    (tmp_path / "CLAUDE.md").write_text("# Test Project\nThis is a test project.\n")
    return tmp_path


def run_claude_prompt(prompt: str, project_dir: Path, timeout: int = 30) -> str:
    """Run a prompt through claude CLI and return the response text."""
    system_prompt = f"{NO_PERSONA}\n\n{STATIC_SYSTEM_PROMPT}"

    # Write the system prompt to a temp file
    prompt_file = project_dir / ".test_system_prompt.md"
    prompt_file.write_text(system_prompt)

    cmd = [
        "claude", "-p",
        "--output-format", "stream-json",
        "--dangerously-skip-permissions",
        "--append-system-prompt-file", str(prompt_file),
        "--", prompt,
    ]

    result = subprocess.run(
        cmd,
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    # Parse stream-json output to extract text
    text_parts = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("type") == "assistant":
            blocks = data.get("message", {}).get("content", [])
            for b in blocks:
                if b.get("type") == "text":
                    text_parts.append(b.get("text", ""))
        elif data.get("type") == "result":
            r = data.get("result", "")
            if isinstance(r, str) and r:
                text_parts.append(r)

    return "\n".join(text_parts)
