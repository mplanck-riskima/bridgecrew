import pytest
from pathlib import Path

pytest.importorskip("faster_whisper", reason="faster-whisper not installed")


def test_transcribe_hello_world():
    from core.voice_transcriber import VoiceTranscriber
    fixture = (Path(__file__).parent.parent / "fixtures" / "hello.mp3").read_bytes()
    t = VoiceTranscriber()
    result = t._transcribe_sync(fixture)
    assert "hello" in result.lower()
