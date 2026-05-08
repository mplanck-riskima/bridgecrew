# Voice Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable users to send Discord voice messages as prompts; the `.ogg` audio is transcribed locally via faster-whisper and injected into the existing Claude pipeline.

**Architecture:** A new `VoiceTranscriber` singleton (`core/voice_transcriber.py`) holds the faster-whisper `base` model (CPU, int8) and transcribes audio in a thread pool via `asyncio.to_thread` so the event loop is never blocked. `on_message` detects `message.flags.voice` and stores the audio attachment on `QueuedPrompt.voice_attachment`. `_process_prompt` transcribes the audio and prepends the transcript before invoking Claude, same pipeline as text.

**Tech Stack:** `faster-whisper` (WhisperModel, base, int8, CPU), `asyncio.to_thread`, `gtts` (test fixture generation only, test-only dependency)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `requirements.txt` | Modify | Add `faster-whisper>=1.0.0` |
| `requirements-test.txt` | Modify | Add `gtts>=2.5.0` (fixture generation) |
| `core/voice_transcriber.py` | Create | VoiceTranscriber singleton — model loading, sync transcription, async wrapper |
| `tests/fixtures/hello.mp3` | Create | Audio fixture for e2e test (generated once, committed) |
| `tests/test_voice_transcription.py` | Create | E2E test — exercises full transcription pipeline |
| `bot.py` | Modify | Instantiate VoiceTranscriber, attach to bot, handle missing dep gracefully |
| `discord_cogs/claude_prompt.py` | Modify | QueuedPrompt.voice_attachment field + on_message detection + _process_prompt transcription |

---

## Task 1: Add dependencies

**Files:**
- Modify: `requirements.txt`
- Modify: `requirements-test.txt`

- [ ] **Step 1: Update requirements.txt**

Replace the file contents with:
```
discord.py[voice]>=2.3.0
python-dotenv>=1.0.0
httpx>=0.27.0
elevenlabs>=1.0.0
imageio-ffmpeg>=0.5.0
faster-whisper>=1.0.0
```

- [ ] **Step 2: Update requirements-test.txt**

Replace the file contents with:
```
pytest>=8.0
pytest-asyncio>=0.23
pytest-timeout>=2.0
mongomock>=4.1
gtts>=2.5.0
```

- [ ] **Step 3: Install new dependencies**

```bash
pip install faster-whisper gtts
```

Expected: packages install without errors.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt requirements-test.txt
git commit -m "chore: add faster-whisper and gtts dependencies"
```

---

## Task 2: Create VoiceTranscriber + E2E test + generate fixture

**Files:**
- Create: `core/voice_transcriber.py`
- Create: `tests/test_voice_transcription.py`
- Create: `tests/fixtures/hello.mp3` (generated, then committed)

- [ ] **Step 1: Write the failing test**

Create `tests/test_voice_transcription.py`:

```python
from pathlib import Path


def test_transcribe_hello_world():
    from core.voice_transcriber import VoiceTranscriber
    fixture = Path("tests/fixtures/hello.mp3").read_bytes()
    t = VoiceTranscriber()
    result = t._transcribe_sync(fixture)
    assert "hello" in result.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_voice_transcription.py::test_transcribe_hello_world -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.voice_transcriber'` or `FileNotFoundError` for fixture.

- [ ] **Step 3: Generate the audio fixture**

Run this Python snippet from the project root:

```bash
python -c "
from gtts import gTTS
from pathlib import Path
Path('tests/fixtures').mkdir(parents=True, exist_ok=True)
tts = gTTS('hello world', lang='en')
tts.save('tests/fixtures/hello.mp3')
print('Generated tests/fixtures/hello.mp3')
"
```

Expected: `Generated tests/fixtures/hello.mp3`

- [ ] **Step 4: Create core/voice_transcriber.py**

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_voice_transcription.py::test_transcribe_hello_world -v
```

Expected: PASS. First run may take 10-30s while faster-whisper downloads the `base` model (~150MB) and loads it. Subsequent runs are faster (~3-5s).

- [ ] **Step 6: Commit**

```bash
git add core/voice_transcriber.py tests/test_voice_transcription.py tests/fixtures/hello.mp3
git commit -m "feat: add VoiceTranscriber with faster-whisper and e2e test"
```

---

## Task 3: Wire VoiceTranscriber into bot.py

**Files:**
- Modify: `bot.py:51-53` (inside `ClaudeBot.__init__`)

- [ ] **Step 1: Add VoiceTranscriber instantiation to ClaudeBot.__init__**

In `bot.py`, in `ClaudeBot.__init__`, after the `self.voice_notifier = VoiceNotifier(self)` line (line ~52), add:

```python
        try:
            from core.voice_transcriber import VoiceTranscriber
            self.voice_transcriber: "VoiceTranscriber | None" = VoiceTranscriber()
        except ImportError:
            log.warning("faster-whisper not installed — voice message transcription disabled.")
            self.voice_transcriber = None
```

The result should look like:

```python
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=intents)
        self.claude_runner = ClaudeRunner()
        self.voice_notifier = VoiceNotifier(self)
        try:
            from core.voice_transcriber import VoiceTranscriber
            self.voice_transcriber: "VoiceTranscriber | None" = VoiceTranscriber()
        except ImportError:
            log.warning("faster-whisper not installed — voice message transcription disabled.")
            self.voice_transcriber = None
        self.workspace_dir = Path(WORKSPACE_DIR)
        self.project_manager = ProjectManager(
            workspace_dir=WORKSPACE_DIR,
            guild_id=int(GUILD_ID),
            channel_id=int(CHANNEL_ID),
        )
        self._restart_requested = False
        self._restart_channel = None
        self._on_worker_done: list = []
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "
import os
os.environ.setdefault('DISCORD_TOKEN', 'x')
os.environ.setdefault('DISCORD_GUILD_ID', '1')
os.environ.setdefault('DISCORD_CHANNEL_ID', '1')
os.environ.setdefault('WORKSPACE_DIR', '.')
from bot import ClaudeBot
b = ClaudeBot()
print('voice_transcriber:', b.voice_transcriber)
"
```

Expected: `voice_transcriber: <core.voice_transcriber.VoiceTranscriber object at 0x...>`

- [ ] **Step 3: Commit**

```bash
git add bot.py
git commit -m "feat: wire VoiceTranscriber into ClaudeBot"
```

---

## Task 4: Detect voice messages in on_message + add QueuedPrompt field

**Files:**
- Modify: `discord_cogs/claude_prompt.py`

This task makes two changes to `claude_prompt.py`:
1. Adds `voice_attachment` field to `QueuedPrompt`
2. Detects voice messages in `on_message` and passes them through

- [ ] **Step 1: Add voice_attachment field to QueuedPrompt dataclass**

Find the `QueuedPrompt` dataclass (around line 209). Change:

```python
@dataclass
class QueuedPrompt:
    message: discord.Message
    prompt: str
    project: object  # Project dataclass
    was_queued: bool = False  # True if this prompt waited behind another
    attachments: list = field(default_factory=list)  # discord.Attachment objects
    cancelled: bool = False
    queue_message: object = None  # discord.Message showing the queued notification
```

To:

```python
@dataclass
class QueuedPrompt:
    message: discord.Message
    prompt: str
    project: object  # Project dataclass
    was_queued: bool = False  # True if this prompt waited behind another
    attachments: list = field(default_factory=list)  # discord.Attachment objects
    cancelled: bool = False
    queue_message: object = None  # discord.Message showing the queued notification
    voice_attachment: object = None  # discord.Attachment for Discord voice messages
```

- [ ] **Step 2: Update on_message to detect voice messages and relax empty-prompt guard**

In `on_message`, find the block that strips the mention and guards against empty prompts (around line 419). Replace:

```python
        # Strip the bot mention from the prompt
        prompt = self._strip_mention(message.content)

        if not prompt:
            await message.channel.send("Send a prompt after mentioning me.")
            return
```

With:

```python
        # Strip the bot mention from the prompt
        prompt = self._strip_mention(message.content)
        voice_att = message.attachments[0] if message.flags.voice and message.attachments else None

        if not prompt and not voice_att:
            await message.channel.send("Send a prompt after mentioning me.")
            return
```

- [ ] **Step 3: Pass voice_attachment in the main-channel QueuedPrompt construction**

In the main-channel branch (inside `if not isinstance(message.channel, discord.Thread):`), find:

```python
            queued = QueuedPrompt(message=message, prompt=prompt, project=None, attachments=list(message.attachments))
```

Change to:

```python
            queued = QueuedPrompt(message=message, prompt=prompt, project=None, attachments=list(message.attachments), voice_attachment=voice_att)
```

- [ ] **Step 4: Pass voice_attachment in the thread QueuedPrompt construction**

In the thread branch (after `# --- Thread @mention ---`), find:

```python
        queued = QueuedPrompt(message=message, prompt=prompt, project=project, attachments=list(message.attachments))
```

Change to:

```python
        queued = QueuedPrompt(message=message, prompt=prompt, project=project, attachments=list(message.attachments), voice_attachment=voice_att)
```

- [ ] **Step 5: Verify syntax**

```bash
python -c "import discord_cogs.claude_prompt; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add discord_cogs/claude_prompt.py
git commit -m "feat: detect Discord voice messages and store on QueuedPrompt"
```

---

## Task 5: Transcribe voice in _process_prompt

**Files:**
- Modify: `discord_cogs/claude_prompt.py:1446-1452` (after attachment download block)

- [ ] **Step 1: Add voice transcription block in _process_prompt**

In `_process_prompt`, find the attachment download block (around line 1446):

```python
        # Download any attachments and append file paths to the prompt
        downloaded_files = await self._download_attachments(item.attachments, project_dir, message.id)
        if downloaded_files:
            prompt += "\n\nThe following files were attached to this message:\n"
            for fp in downloaded_files:
                prompt += f"- {fp.resolve()}\n"
```

Immediately after this block, add:

```python
        # Transcribe voice messages and inject transcript as prompt text
        if item.voice_attachment is not None:
            if self.bot.voice_transcriber is None:
                await message.channel.send(
                    "❌ Voice transcription is not available — `faster-whisper` is not installed."
                )
                return
            try:
                transcript = await self.bot.voice_transcriber.transcribe(item.voice_attachment)
            except Exception:
                log.exception("Voice transcription failed")
                await message.channel.send(
                    "❌ Voice transcription failed — please send a text message instead."
                )
                return
            if not transcript:
                await message.channel.send(
                    "🎙️ Couldn't make out any speech — please try again."
                )
                return
            await message.channel.send(f'🎙️ *Transcribed:* "{transcript}"')
            if prompt:
                prompt = f"{prompt}\n\n[Voice message]: {transcript}"
            else:
                prompt = transcript
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "import discord_cogs.claude_prompt; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add discord_cogs/claude_prompt.py
git commit -m "feat: transcribe voice messages in _process_prompt and inject as prompt"
```
