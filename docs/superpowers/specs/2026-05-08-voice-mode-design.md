# Voice Mode — Design Spec
**Date:** 2026-05-08  
**Feature:** voice-mode  
**Status:** Approved

## Overview

Allow users to send Discord voice messages as prompts to the bot. A voice message's audio is transcribed locally via faster-whisper and the transcript is passed into the existing Claude pipeline unchanged.

## Architecture

### New file: `core/voice_transcriber.py`

A singleton `VoiceTranscriber` class that owns the faster-whisper model.

- Model: `WhisperModel("base", device="cpu", compute_type="int8")` — int8 quantization reduces RAM and speeds up CPU inference.
- Model is lazy-loaded on first transcription call so bot startup is unaffected.
- All CPU-bound work runs in `asyncio.to_thread()` — the event loop stays free and the bot remains responsive on all channels during transcription.

```
VoiceTranscriber
  ├── _model: WhisperModel (lazy-loaded in thread)
  ├── async transcribe(attachment) -> str
  │     ├── await attachment.read()           # async I/O
  │     └── await asyncio.to_thread(          # CPU offloaded
  │               _transcribe_sync, bytes)
  └── _transcribe_sync(bytes) -> str          # runs in ThreadPoolExecutor
        ├── write bytes to NamedTemporaryFile
        ├── model.transcribe(tmp_path)
        ├── join segment texts
        └── unlink temp file
```

### Changed: `discord_cogs/claude_prompt.py`

**`QueuedPrompt` dataclass** — one new optional field:
```python
voice_attachment: discord.Attachment | None = None
```

**`on_message`** — after stripping the mention, detect voice messages:
```python
# discord.py 2.7.x: voice messages set message.flags.voice
if message.flags.voice and message.attachments:
    voice_att = message.attachments[0]
```
- If found, set `queued.voice_attachment = voice_att` and allow empty `prompt` (typed text may be blank).
- Existing empty-prompt guard is relaxed to pass through when `voice_attachment` is set.

**`_process_prompt`** — before handing the prompt to Claude, if `item.voice_attachment` is set:
1. Call `await self.bot.voice_transcriber.transcribe(item.voice_attachment)`
2. Post `🎙️ *Transcribed: "<text>"*` to the channel
3. If typed text is also present: `prompt = f"{typed_text}\n\n[Voice message]: {transcript}"`
4. Otherwise: `prompt = transcript`

### Changed: `bot.py`

Instantiate and attach:
```python
from core.voice_transcriber import VoiceTranscriber
self.voice_transcriber = VoiceTranscriber()
```

If `faster-whisper` is not installed, log a warning and set `self.voice_transcriber = None`. `_process_prompt` checks for `None` and sends a user-visible error rather than crashing.

### Changed: `requirements.txt`

Add `faster-whisper`.

## Data Flow

```
User sends voice message @mentioning bot
  → on_message: detects voice_attachment flag on attachment
  → QueuedPrompt(prompt="", voice_attachment=att) queued normally
  → worker picks up item → _process_prompt
  → await bot.voice_transcriber.transcribe(att)
      → att.read() [async]
      → asyncio.to_thread(_transcribe_sync) [CPU in thread]
  → channel.send("🎙️ Transcribed: ...")
  → prompt = transcript
  → existing Claude pipeline (session, feature gate, etc.) unchanged
```

## Error Handling

| Scenario | Behavior |
|---|---|
| Transcription exception | Send `❌ Voice transcription failed — please send a text message instead.` and return early |
| Empty transcript (silence/noise) | Send `🎙️ Couldn't make out any speech — please try again.` and return early |
| Voice message with no @mention | Ignored — existing mention guard unchanged |
| Voice message + typed text | Transcript appended: `{typed_text}\n\n[Voice message]: {transcript}` |
| faster-whisper not installed | `voice_transcriber = None`; voice messages get a friendly error, text prompts unaffected |

## Testing

**E2E test:** `tests/test_voice_transcription.py`

A pre-recorded fixture `tests/fixtures/hello.ogg` (a short "hello world" clip) is committed to the repo. The test exercises the full transcription pipeline — real model, real temp file, real faster-whisper output — with no mocking.

```python
def test_transcribe_hello_world():
    from core.voice_transcriber import VoiceTranscriber
    fixture = Path("tests/fixtures/hello.ogg").read_bytes()
    t = VoiceTranscriber()
    result = t._transcribe_sync(fixture)
    assert "hello" in result.lower()
```

The fixture file is generated once via any TTS tool and committed. Running the test requires `faster-whisper` installed and takes ~3–5s on CPU.

## Dependencies

- `faster-whisper` (pip) — wraps CTranslate2-based Whisper inference
- No new API keys or external services required
- ffmpeg not required for transcription (faster-whisper reads OGG/Opus natively)

## Out of Scope

- Streaming transcription (not supported by faster-whisper)
- Voice language selection (faster-whisper auto-detects)
- Transcription confidence scores or fallback prompting
