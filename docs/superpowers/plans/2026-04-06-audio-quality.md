# Audio Quality Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the low-quality `audioop` PCM resampler with an FFmpeg-backed MP3 pipeline to eliminate crackling artifacts in Discord voice playback.

**Architecture:** ElevenLabs is asked for 192 kbps MP3 (falling back to 128 kbps) instead of raw PCM. The MP3 bytes are passed directly to `discord.FFmpegPCMAudio(..., pipe=True)`, which uses the already-installed FFmpeg binary to decode and resample to Discord's required 48 kHz stereo PCM — eliminating all manual resampling.

**Tech Stack:** Python, discord.py[voice], httpx, FFmpeg (system binary, already required)

---

## File Map

| Action | Path |
|--------|------|
| Modify | `core/voice_notifier.py` |
| Create | `tests/bot/test_voice_notifier.py` |

---

### Task 1: Write failing tests for the new MP3 pipeline

**Files:**
- Create: `tests/bot/test_voice_notifier.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for VoiceNotifier MP3 pipeline."""
from unittest.mock import MagicMock, patch, AsyncMock
import pytest
from core.voice_notifier import VoiceNotifier


@pytest.fixture
def notifier():
    bot = MagicMock()
    return VoiceNotifier(bot)


class TestCallTts:
    def test_returns_mp3_bytes_on_200(self, notifier):
        fake_bytes = b"fake-mp3-data"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = fake_bytes

        with patch("core.voice_notifier.httpx.post", return_value=mock_resp) as mock_post:
            result = notifier._call_tts("hello", api_key="key", voice_id="voice123")

        assert result == fake_bytes
        # Must request an MP3 format, not PCM
        call_kwargs = mock_post.call_args
        assert "mp3" in call_kwargs.kwargs["params"]["output_format"]

    def test_falls_back_to_lower_bitrate_on_403(self, notifier):
        fake_bytes = b"fake-mp3-128"
        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.content = fake_bytes

        with patch("core.voice_notifier.httpx.post", side_effect=[resp_403, resp_200]):
            result = notifier._call_tts("hello", api_key="key", voice_id="voice123")

        assert result == fake_bytes

    def test_returns_none_on_non_403_error(self, notifier):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "server error"

        with patch("core.voice_notifier.httpx.post", return_value=mock_resp):
            result = notifier._call_tts("hello", api_key="key", voice_id="voice123")

        assert result is None


class TestCallSfx:
    def test_returns_mp3_bytes_on_200(self, notifier):
        fake_bytes = b"fake-sfx-mp3"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = fake_bytes

        with patch("core.voice_notifier.httpx.post", return_value=mock_resp) as mock_post:
            result = notifier._call_sfx("explosion", api_key="key")

        assert result == fake_bytes
        call_kwargs = mock_post.call_args
        assert "mp3" in call_kwargs.kwargs["params"]["output_format"]

    def test_returns_none_when_all_formats_403(self, notifier):
        resp_403 = MagicMock()
        resp_403.status_code = 403

        with patch("core.voice_notifier.httpx.post", return_value=resp_403):
            result = notifier._call_sfx("explosion", api_key="key")

        assert result is None


class TestPlay:
    @pytest.mark.asyncio
    async def test_uses_ffmpeg_audio_source(self, notifier):
        import io
        import discord

        mp3_bytes = b"fake-mp3"
        guild = MagicMock(spec=discord.Guild)
        guild.voice_client = None

        voice_client = AsyncMock(spec=discord.VoiceClient)
        voice_client.is_connected.return_value = True

        voice_channel = AsyncMock(spec=discord.VoiceChannel)
        voice_channel.connect.return_value = voice_client

        captured = {}

        def fake_play(source, after=None):
            captured["source"] = source
            if after:
                after(None)

        voice_client.play = fake_play

        with patch("core.voice_notifier.discord.FFmpegPCMAudio") as mock_ffmpeg:
            mock_ffmpeg.return_value = MagicMock()
            await notifier._play(guild, voice_channel, mp3_bytes)

        mock_ffmpeg.assert_called_once()
        call_args = mock_ffmpeg.call_args
        # pipe=True must be set
        assert call_args.kwargs.get("pipe") is True
        # source must be a BytesIO containing the mp3 bytes
        source_arg = call_args.args[0]
        assert isinstance(source_arg, io.BytesIO)
        assert source_arg.read() == mp3_bytes
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd M:/bridgecrew && python -m pytest tests/bot/test_voice_notifier.py -v
```

Expected: failures referencing `mp3` formats not being used and possibly import errors.

---

### Task 2: Rewrite `core/voice_notifier.py`

**Files:**
- Modify: `core/voice_notifier.py`

- [ ] **Step 1: Replace the file contents**

Replace the entire file with the following:

```python
import asyncio
import io
import logging
import os

import discord
import httpx

log = logging.getLogger(__name__)

ELEVENLABS_BASE = "https://api.elevenlabs.io"


class VoiceNotifier:
    """Generates audio via ElevenLabs and plays it in a configured Discord voice channel.

    Configuration via environment variables:
      NOTIFY_VOICE_CHANNEL_ID  — Discord voice channel ID to join
      ELEVENLABS_API_KEY       — ElevenLabs API key
      ELEVENLABS_VOICE_ID      — Voice ID for TTS (default: JBFqnCBsd6RMkjVDRZzb)

    Routing:
      - Prompt starts with "speak:" → ElevenLabs TTS endpoint (speech)
      - Everything else             → ElevenLabs Sound Effects endpoint (sfx/ambient/music)

    All errors are logged and swallowed — audio is best-effort and never blocks the bot.
    """

    def __init__(self, bot) -> None:
        self._bot = bot
        # Serialize concurrent play_prompt calls so we don't stomp the voice client
        self._lock = asyncio.Lock()

    def _route(self, prompt: str) -> tuple[str, str]:
        """Returns ('tts', text) or ('sfx', description)."""
        if prompt.lower().startswith("speak:"):
            return "tts", prompt[6:].strip()
        return "sfx", prompt

    # MP3 formats in descending quality order; ElevenLabs gates higher bitrates by tier.
    # Pro/Creator: mp3_44100_192 | Starter and above: mp3_44100_128
    _MP3_FORMATS = ["mp3_44100_192", "mp3_44100_128"]

    def _call_tts(self, text: str, api_key: str, voice_id: str) -> bytes | None:
        """Call ElevenLabs TTS, trying MP3 formats from best to lowest quality."""
        for fmt in self._MP3_FORMATS:
            resp = httpx.post(
                f"{ELEVENLABS_BASE}/v1/text-to-speech/{voice_id}",
                params={"output_format": fmt},
                headers={"xi-api-key": api_key},
                json={"text": text, "model_id": "eleven_turbo_v2_5"},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.content
            if resp.status_code != 403:
                log.warning("ElevenLabs TTS HTTP %s: %s", resp.status_code, resp.text[:200])
                return None
            log.debug("ElevenLabs TTS: %s not available on this tier, trying lower bitrate.", fmt)
        log.warning("ElevenLabs TTS: no MP3 format available on this subscription tier.")
        return None

    def _call_sfx(self, description: str, api_key: str) -> bytes | None:
        """Call ElevenLabs Sound Effects, trying MP3 formats from best to lowest quality."""
        for fmt in self._MP3_FORMATS:
            resp = httpx.post(
                f"{ELEVENLABS_BASE}/v1/sound-generation",
                params={"output_format": fmt},
                headers={"xi-api-key": api_key},
                json={"text": description},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.content
            if resp.status_code != 403:
                log.warning("ElevenLabs SFX HTTP %s: %s", resp.status_code, resp.text[:200])
                return None
            log.debug("ElevenLabs SFX: %s not available on this tier, trying lower bitrate.", fmt)
        log.warning("ElevenLabs SFX: no MP3 format available on this subscription tier.")
        return None

    async def _generate_audio(self, prompt: str, api_key: str, voice_id: str) -> bytes | None:
        """Generate MP3 audio from the prompt. Runs in a thread pool."""
        kind, content = self._route(prompt)
        try:
            if kind == "tts":
                return await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self._call_tts(content, api_key, voice_id)
                )
            else:
                return await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self._call_sfx(content, api_key)
                )
        except Exception:
            log.exception("Audio generation failed for prompt: %r", prompt[:80])
            return None

    async def play_prompt(self, guild: discord.Guild, prompt: str) -> None:
        """Generate and play audio for a [play-audio:] marker prompt."""
        channel_id = os.getenv("NOTIFY_VOICE_CHANNEL_ID")
        api_key = os.getenv("ELEVENLABS_API_KEY")
        voice_id = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")

        if not channel_id or not api_key:
            log.debug("Voice notify skipped — NOTIFY_VOICE_CHANNEL_ID or ELEVENLABS_API_KEY not set.")
            return

        voice_channel = guild.get_channel(int(channel_id))
        if not isinstance(voice_channel, discord.VoiceChannel):
            log.warning("NOTIFY_VOICE_CHANNEL_ID %s is not a VoiceChannel.", channel_id)
            return

        audio_bytes = await self._generate_audio(prompt, api_key, voice_id)
        if not audio_bytes:
            return

        async with self._lock:
            await self._play(guild, voice_channel, audio_bytes)

    async def voice_event(self, guild: discord.Guild, event: str, message: str) -> None:
        """Play a canned TTS notification for an autonomous bot event."""
        from core.state import load_config
        enabled_events = load_config().get("voice_events", [])
        if event not in enabled_events:
            return
        await self.play_prompt(guild, f"speak: {message}")

    async def _play(
        self,
        guild: discord.Guild,
        voice_channel: discord.VoiceChannel,
        audio_bytes: bytes,
    ) -> None:
        """Connect, play MP3 audio via FFmpeg, then disconnect."""
        voice_client: discord.VoiceClient | None = None
        try:
            # Disconnect any stale connection first
            if guild.voice_client:
                await guild.voice_client.disconnect(force=True)

            voice_client = await voice_channel.connect()
            done = asyncio.Event()

            def after(error):
                if error:
                    log.warning("Voice playback error: %s", error)
                done.set()

            source = discord.FFmpegPCMAudio(io.BytesIO(audio_bytes), pipe=True)
            voice_client.play(source, after=after)
            await asyncio.wait_for(done.wait(), timeout=60)

        except asyncio.TimeoutError:
            log.warning("Voice playback timed out.")
        except Exception:
            log.exception("Voice playback failed.")
        finally:
            if voice_client and voice_client.is_connected():
                await voice_client.disconnect(force=True)
```

- [ ] **Step 2: Run the tests**

```
cd M:/bridgecrew && python -m pytest tests/bot/test_voice_notifier.py -v
```

Expected output:
```
tests/bot/test_voice_notifier.py::TestCallTts::test_returns_mp3_bytes_on_200 PASSED
tests/bot/test_voice_notifier.py::TestCallTts::test_falls_back_to_lower_bitrate_on_403 PASSED
tests/bot/test_voice_notifier.py::TestCallTts::test_returns_none_on_non_403_error PASSED
tests/bot/test_voice_notifier.py::TestCallSfx::test_returns_mp3_bytes_on_200 PASSED
tests/bot/test_voice_notifier.py::TestCallSfx::test_returns_none_when_all_formats_403 PASSED
tests/bot/test_voice_notifier.py::TestPlay::test_uses_ffmpeg_audio_source PASSED
```

- [ ] **Step 3: Run the full test suite to check for regressions**

```
cd M:/bridgecrew && python -m pytest tests/ -v --ignore=tests/e2e
```

Expected: all previously passing tests still pass.

- [ ] **Step 4: Commit**

```bash
cd M:/bridgecrew
git add core/voice_notifier.py tests/bot/test_voice_notifier.py
git commit -m "fix: replace audioop resampler with FFmpeg MP3 pipeline to fix crackling audio"
```
