# Audio Quality Fix — Design Spec

**Date:** 2026-04-06
**Status:** Approved
**File:** `core/voice_notifier.py`

## Problem

ElevenLabs audio played in the Discord voice channel has crackling and distortion artifacts. The root cause is `audioop.ratecv`, which uses low-quality linear interpolation to resample PCM audio from ElevenLabs rates (44100 or 22050 Hz) to Discord's required 48000 Hz. The conversion ratios are non-integer fractions (e.g. 44100→48000 = 147:160), which cause aliasing and clicking at this quality level. `audioop` is also deprecated in Python 3.11 and removed in 3.13.

## Solution

Replace the PCM pipeline with an MP3 pipeline backed by FFmpeg.

- Request `mp3_44100_192` (192 kbps MP3) from ElevenLabs instead of PCM.
- Fall back to `mp3_44100_128` if the higher bitrate is unavailable (403 response).
- Pass raw MP3 bytes directly to `discord.FFmpegPCMAudio(..., pipe=True)`.
- FFmpeg (already a required system dependency of `discord.py[voice]`) decodes the MP3 and resamples to 48kHz stereo PCM internally at professional quality.
- Remove `_to_discord_pcm`, the `_PCM_FORMATS` ladder, and the `audioop` import entirely.

## Changes to `core/voice_notifier.py`

### Remove
- `import audioop`
- `_PCM_FORMATS` class attribute
- `_to_discord_pcm` method

### Add
- `_MP3_FORMATS` class attribute:
  ```python
  _MP3_FORMATS = [("mp3_44100_192", ), ("mp3_44100_128", )]
  ```
  (No rate value needed — FFmpeg handles all conversion.)

### Modify
- `_call_tts`: iterate `_MP3_FORMATS`, request each `output_format` via the ElevenLabs TTS endpoint, return raw `resp.content` (MP3 bytes) on first 200. Same 403-fallback logic.
- `_call_sfx`: same pattern for the sound-generation endpoint.
- `_generate_audio`: return raw MP3 bytes from `_call_tts`/`_call_sfx` directly. No conversion step.
- `_play`: replace `discord.PCMAudio(io.BytesIO(audio_bytes))` with `discord.FFmpegPCMAudio(io.BytesIO(audio_bytes), pipe=True)`.

## Data Flow

```
ElevenLabs API
  → mp3_44100_192 bytes (or mp3_44100_128 fallback)
  → io.BytesIO(mp3_bytes)
  → discord.FFmpegPCMAudio(..., pipe=True)
  → FFmpeg stdin → decode → resample 44100→48000 → stereo PCM
  → Discord voice channel
```

## What Does Not Change

- Tier-based format fallback logic (403 = try next format)
- `speak:` vs SFX routing
- Lock serialization for concurrent play calls
- Voice event / play_prompt public API
- Environment variable configuration

## Error Handling

No new error handling needed. FFmpeg errors surface as exceptions in `_play`, which are already caught and logged by the existing `except Exception` block.

## Testing

Manual test: trigger a `[play-audio: speak: hello]` and an SFX prompt, confirm no crackling. No automated tests exist for audio playback.
