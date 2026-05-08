import logging
import os
import tempfile

log = logging.getLogger(__name__)


class VoiceTranscriber:
    """Transcribes audio to text using faster-whisper on CPU.

    The WhisperModel is lazy-loaded on first use and kept in memory.
    All CPU-bound work runs via asyncio.to_thread so the event loop stays free.
    """

    def __init__(self) -> None:
        self._model = None

    def _load_model(self):
        from faster_whisper import WhisperModel
        if self._model is None:
            log.info("Loading faster-whisper 'base' model (first use)...")
            self._model = WhisperModel("base", device="cpu", compute_type="int8")
            log.info("faster-whisper model loaded.")
        return self._model

    def _transcribe_sync(self, audio_bytes: bytes) -> str:
        """Transcribe audio bytes to text. Runs in a thread pool executor.

        PyAV (used internally by faster-whisper) probes the audio format from
        the file content, not the extension, so any audio format Discord sends works.
        """
        model = self._load_model()
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp_path = tmp.name
        try:
            tmp.write(audio_bytes)
            tmp.close()
            segments, _ = model.transcribe(tmp_path, beam_size=5)
            return " ".join(s.text for s in segments).strip()
        finally:
            try:
                tmp.close()  # no-op if already closed; ensures file is not locked on Windows
            except Exception:
                pass
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    async def transcribe(self, attachment) -> str:
        """Download a Discord attachment and transcribe it. Non-blocking."""
        import asyncio
        audio_bytes = await attachment.read()
        return await asyncio.to_thread(self._transcribe_sync, audio_bytes)
