# Audio Quality Improvements

## Problem

ElevenLabs audio played in Discord voice channels had crackling and distortion artifacts. The root cause was `audioop.ratecv`, a low-quality linear interpolation resampler used to convert PCM audio from ElevenLabs (44100 or 22050 Hz) to Discord's required 48000 Hz. Non-integer conversion ratios (e.g., 44100→48000 = 147:160) caused aliasing and clicking at audible frequencies. Additionally, `audioop` is deprecated in Python 3.11 and removed in 3.13.

## Solution

**Replaced the PCM pipeline with an FFmpeg-backed MP3 pipeline:**

- ElevenLabs now returns 192 kbps MP3 (falling back to 128 kbps on tier limitations) instead of raw PCM
- MP3 bytes are passed directly to `discord.FFmpegPCMAudio(BytesIO, pipe=True)`
- FFmpeg (bundled via `imageio-ffmpeg` when not in PATH) decodes and resamples at professional quality
- Eliminated the intermediate resampling step entirely

**Enhanced SFX quality with duration and influence control:**

- Sound effects now specify `duration_seconds` and `prompt_influence` parameters to ElevenLabs
- Default 8-second duration with 0.5 prompt influence (previously auto-detected, rushed)
- Users can override duration inline: `[play-audio: celebration (5s)]`

## Key Files Changed

- `core/voice_notifier.py` — Rewrote audio pipeline; removed `audioop`, added MP3 format fallback, FFmpeg integration, duration parsing
- `requirements.txt` — Replaced `audioop-lts` with `imageio-ffmpeg`
- `tests/bot/test_voice_notifier.py` — 7 new tests covering MP3 TTS/SFX and FFmpeg usage
- `dashboard/backend/app/scheduler.py` — Fixed cron scheduler timezone to America/Los_Angeles (PST/PDT)

## Design Decisions

1. **MP3 over PCM resampling** — FFmpeg is battle-tested; MP3 at 192 kbps is transparent quality for voice/SFX
2. **Bundled FFmpeg via imageio-ffmpeg** — No system dependency, works cross-platform, auto-detected
3. **Thread-safe event callback** — Used `loop.call_soon_threadsafe()` to safely signal playback completion from `AudioPlayer` daemon thread
4. **Prompt-parsed duration** — Allows flexible SFX timing without API changes; simple regex pattern `(Ns)` at end of description
5. **Default 8s SFX duration** — Balances typical celebration/notification needs; easily overrideable

## Tradeoffs

- MP3 is lossy, but 192 kbps is imperceptible for voice and SFX
- FFmpeg subprocess overhead minimal (one-time per audio playback)
- Duration parsing is simple regex; no validation of range (relies on ElevenLabs 0.5–30s bounds)

## Testing

- 7 unit tests: format fallback, MP3 request validation, FFmpeg integration, error handling
- All bot tests pass (68 total)
- Manual testing: TTS quality excellent; SFX now takes proper duration instead of rushing

## Known Limitations & Follow-up

- No voice settings for TTS (stability, similarity_boost, style) — could be added via environment variables or inline syntax
- SFX `prompt_influence` fixed at 0.5 — could be made configurable if needed
- Duration parsing doesn't validate ElevenLabs bounds (0.5–30s) — client-side validation optional
- Cron scheduler timezone hardcoded to America/Los_Angeles — could be configurable via `.env`

## Commits

- `5587f41` — Test: add failing tests for MP3 audio pipeline
- `020ce96` — test: improve voice_notifier test quality - format assertions and cleanup
- `25563c7` — fix: replace audioop resampler with FFmpeg MP3 pipeline to fix crackling audio
- `99a2296` — fix: thread-safe event callback and remove deprecated asyncio.get_event_loop
- `d664464` — fix: use bundled ffmpeg via imageio-ffmpeg when system ffmpeg not in PATH
- `bc803b2` — fix: add duration and prompt_influence to SFX calls to fix rushed audio
- `641b291` — fix: use America/Los_Angeles timezone for cron scheduler (PST/PDT)
