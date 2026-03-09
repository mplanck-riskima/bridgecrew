import asyncio
import json
import logging
import os
from collections.abc import AsyncGenerator
from pathlib import Path

from models.session import StreamEvent

log = logging.getLogger(__name__)


class ClaudeRunner:
    def __init__(self) -> None:
        # channel/thread id -> running subprocess
        self._active: dict[int, asyncio.subprocess.Process] = {}
        self._cancelled: set[int] = set()

    def is_busy(self, thread_id: int) -> bool:
        proc = self._active.get(thread_id)
        return proc is not None and proc.returncode is None

    def was_cancelled(self, thread_id: int) -> bool:
        return thread_id in self._cancelled

    def cancel(self, thread_id: int) -> bool:
        proc = self._active.get(thread_id)
        if proc and proc.returncode is None:
            self._cancelled.add(thread_id)
            proc.kill()
            return True
        return False

    async def cancel_all(self) -> None:
        for thread_id, proc in list(self._active.items()):
            if proc.returncode is None:
                proc.kill()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass
        self._active.clear()
        self._cancelled.clear()

    async def run(
        self,
        prompt: str,
        project_dir: Path,
        thread_id: int,
        session_id: str | None = None,
        resume: bool = False,
    ) -> AsyncGenerator[StreamEvent, None]:
        if self.is_busy(thread_id):
            yield StreamEvent(type="error", content="Claude is already running for this project.")
            return

        cmd = ["claude", "-p", "--output-format", "stream-json"]

        if resume and session_id:
            cmd.extend(["--resume", "--session-id", session_id, "--fork-session"])
        elif session_id:
            cmd.extend(["--continue", "--session-id", session_id, "--fork-session"])

        cmd.append(prompt)

        # Build clean environment — remove CLAUDECODE to avoid nested-session refusal
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(project_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._active[thread_id] = proc

            async for event in self._parse_stream(proc):
                yield event

            # Check for errors on stderr
            stderr_data = await proc.stderr.read()
            if proc.returncode != 0 and stderr_data:
                yield StreamEvent(
                    type="error",
                    content=f"Claude exited with code {proc.returncode}: {stderr_data.decode(errors='replace')[:500]}",
                )

        except FileNotFoundError:
            yield StreamEvent(type="error", content="Claude CLI not found. Make sure `claude` is installed and on PATH.")
        except Exception as e:
            yield StreamEvent(type="error", content=f"Failed to run Claude: {e}")
        finally:
            was_cancelled = thread_id in self._cancelled
            self._cancelled.discard(thread_id)
            self._active.pop(thread_id, None)
            if was_cancelled:
                yield StreamEvent(type="cancelled")

    async def _parse_stream(
        self, proc: asyncio.subprocess.Process
    ) -> AsyncGenerator[StreamEvent, None]:
        assert proc.stdout is not None

        buffer = b""
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break

            buffer += chunk
            lines = buffer.split(b"\n")
            # Keep the last incomplete line in the buffer
            buffer = lines[-1]

            for line in lines[:-1]:
                line = line.strip()
                if not line:
                    continue
                event = self._parse_line(line)
                if event:
                    yield event

        # Process any remaining buffer
        if buffer.strip():
            event = self._parse_line(buffer.strip())
            if event:
                yield event

    def _parse_line(self, line: bytes) -> StreamEvent | None:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            log.warning("Skipping malformed JSON line: %s", line[:200])
            return None

        msg_type = data.get("type", "")

        # Handle assistant message content blocks
        if msg_type == "content_block_delta":
            delta = data.get("delta", {})
            if delta.get("type") == "text_delta":
                return StreamEvent(type="text", content=delta.get("text", ""))

        # Handle result/final message
        if msg_type == "result":
            result = data.get("result", "")
            session_id = data.get("session_id")
            cost = None
            cost_data = data.get("cost_usd")
            if cost_data is not None:
                cost = float(cost_data)
            return StreamEvent(
                type="result",
                content=result if isinstance(result, str) else "",
                session_id=session_id,
                cost_usd=cost,
            )

        return None
