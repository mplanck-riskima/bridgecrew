"""Tests for VoiceNotifier MP3 pipeline."""
from unittest.mock import MagicMock, patch, AsyncMock
import pytest
import io
import discord

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
        params = mock_post.call_args.kwargs.get("params") or {}
        assert "mp3" in params.get("output_format", "")

    def test_falls_back_to_lower_bitrate_on_403(self, notifier):
        fake_bytes = b"fake-mp3-128"
        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.content = fake_bytes

        with patch("core.voice_notifier.httpx.post", side_effect=[resp_403, resp_200]) as mock_post:
            result = notifier._call_tts("hello", api_key="key", voice_id="voice123")

        assert result == fake_bytes
        calls = mock_post.call_args_list
        assert calls[0].kwargs["params"]["output_format"] == "mp3_44100_192"
        assert calls[1].kwargs["params"]["output_format"] == "mp3_44100_128"

    def test_returns_none_on_non_403_error(self, notifier):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "server error"

        with patch("core.voice_notifier.httpx.post", return_value=mock_resp):
            result = notifier._call_tts("hello", api_key="key", voice_id="voice123")

        assert result is None

    def test_returns_none_when_all_formats_403(self, notifier):
        resp_403 = MagicMock()
        resp_403.status_code = 403

        with patch("core.voice_notifier.httpx.post", return_value=resp_403):
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
        params = mock_post.call_args.kwargs.get("params") or {}
        assert "mp3" in params.get("output_format", "")

    def test_returns_none_when_all_formats_403(self, notifier):
        resp_403 = MagicMock()
        resp_403.status_code = 403

        with patch("core.voice_notifier.httpx.post", return_value=resp_403):
            result = notifier._call_sfx("explosion", api_key="key")

        assert result is None


class TestPlay:
    @pytest.mark.asyncio
    async def test_uses_ffmpeg_audio_source(self, notifier):
        mp3_bytes = b"fake-mp3"
        guild = MagicMock(spec=discord.Guild)
        guild.voice_client = None

        voice_client = AsyncMock(spec=discord.VoiceClient)
        voice_client.is_connected.return_value = True

        voice_channel = AsyncMock(spec=discord.VoiceChannel)
        voice_channel.connect.return_value = voice_client

        def fake_play(source, after=None):
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
