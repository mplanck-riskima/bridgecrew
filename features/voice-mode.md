# voice-mode

**Started:** 2026-05-07  
**Completed:** 2026-05-08  
**Cost:** $7.0759

## Summary

Adds Discord voice message transcription to the bot using faster-whisper (OpenAI Whisper running locally on CPU). When a user sends a Discord voice message in a project thread, the bot detects it via `message.flags.voice`, downloads the OGG Opus attachment, transcribes it asynchronously via `VoiceTranscriber` (`core/voice_transcriber.py`), echoes the transcript back to the channel with a 🎙️ prefix, and injects it as the prompt text before executing Claude. The Whisper "base" model is lazy-loaded on first use and kept in memory with a thread-safe lock. Voice attachments are excluded from regular file injection. Graceful fallback is included: if `faster-whisper` is not installed, the bot sends an error message instead of crashing. Key files: `core/voice_transcriber.py` (new), `bot.py` (wires in VoiceTranscriber with ImportError guard), `discord_cogs/claude_prompt.py` (voice detection on QueuedPrompt, transcription in `_process_prompt`), `requirements.txt` / `requirements-test.txt` (adds faster-whisper + gtts). E2E tests added in `tests/e2e/test_voice_transcription.py` with an OGG Opus fixture.
