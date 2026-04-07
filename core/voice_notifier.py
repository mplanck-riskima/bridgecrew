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
                return await asyncio.get_running_loop().run_in_executor(
                    None, lambda: self._call_tts(content, api_key, voice_id)
                )
            else:
                return await asyncio.get_running_loop().run_in_executor(
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
            loop = asyncio.get_running_loop()
            done = asyncio.Event()

            def after(error):
                if error:
                    log.warning("Voice playback error: %s", error)
                loop.call_soon_threadsafe(done.set)

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
