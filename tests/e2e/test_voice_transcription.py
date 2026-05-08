import pytest
from pathlib import Path

pytest.importorskip("faster_whisper", reason="faster-whisper not installed")

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_transcribe_hello_world():
    from core.voice_transcriber import VoiceTranscriber
    fixture = (FIXTURES / "hello.mp3").read_bytes()
    t = VoiceTranscriber()
    result = t._transcribe_sync(fixture)
    assert "hello" in result.lower()


def test_transcribe_ogg_opus():
    """OGG Opus is the exact format Discord sends for voice messages."""
    from core.voice_transcriber import VoiceTranscriber
    fixture = (FIXTURES / "hello_discord.ogg").read_bytes()
    t = VoiceTranscriber()
    result = t._transcribe_sync(fixture)
    assert "hello" in result.lower()
