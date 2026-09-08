# IO Phase 4 — Voice (speech in, speech out) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `io listen` — press a hotkey, speak, IO transcribes it, runs it through the existing service, and **speaks the answer back in a local female voice**. Plus passive (hands-free) mode behind a config flag, and `io doctor` to check the whole local stack.

**Architecture:** Two new deterministic seams — `Transcriber` (speech → text) and `Speaker` (text → speech) — each a `Protocol` with a real adapter (`faster-whisper`, Piper) and a `Fake` for tests. All orchestration (the listen loop, markdown-to-prose flattening, VAD segmentation, `io doctor` checks) is plain Python tested without hardware. The voice client is a **client of `io serve`** (Plan 3) — capture → transcribe → `POST /utterance` → speak — so voice reuses the one pipeline. TTS is post-processing: it never calls the model, never touches storage.

**Tech Stack:** Python 3.11+, `uv`. New deps (all lazy-imported, graceful-degrading): `faster-whisper`, `piper-tts` (or a `piper` binary), `sounddevice`, `pynput` (hotkey), `webrtcvad` (passive VAD). `httpx` (already present) for the service client.

**Spec:** `docs/superpowers/specs/2026-09-07-io-phase-1-design.md` §6 + **§6.1 (spoken output — added 2026-09-08)**, §11 stages 16–19, §13.2/§13.3 (profiles, budget), `.claude/knowledge/local-stack.md`.

## Global Constraints

- **Python** ≥ 3.11, `uv` for everything.
- **Local-first (hard rule):** Whisper and Piper run entirely locally; voice
  model files are downloaded once into `voices_dir` and never fetched at
  run time. The voice client talks only to `io serve` on `127.0.0.1`. No cloud
  STT/TTS, ever.
- **LLM boundary:** `Transcriber` and `Speaker` are deterministic I/O — they
  never call `Backend`. `flatten_markdown()` is pure string work. A missing
  Whisper/Piper model **degrades gracefully** (text-only, one-line warning) —
  never a crash, never a silent drop of the user's utterance.
- **Resource budget (§13.3):** Whisper model size comes from
  `backend.profile` (`light`→`base`, `quality`→`small`). Passive mode keeps only
  VAD + (on a segment) Whisper resident; the instruct model still loads
  on-demand per utterance.
- **TDD:** failing test first. Hardware/model adapters (`WhisperTranscriber`,
  `PiperSpeaker`, mic, hotkey) are exercised by `@pytest.mark.voice` tests that
  run only when `IO_VOICE_TESTS=1`; everything else uses `FakeTranscriber` /
  `FakeSpeaker` / a fake service client and runs in normal CI.
- Package `io_assistant`. DB tests need `IO_TEST_DATABASE_URL`.

---

## File Structure

```
io_assistant/
  speak/
    __init__.py
    interface.py     # Speaker Protocol, SpeakError
    text.py          # flatten_markdown(): markdown/answer -> plain prose
    piper.py         # PiperSpeaker (piper-tts package or `piper` binary) + synth-to-wav + playback
  transcribe/
    __init__.py
    interface.py     # Transcriber Protocol, TranscribeError, Transcript
    whisper.py       # WhisperTranscriber (faster-whisper), model size from profile
  capture/
    __init__.py
    audio.py         # record_until_release() / record_fixed() seams (sounddevice)
    hotkey.py        # push_to_talk(): pynput global hotkey -> callback seam
    vad.py           # segment_stream(): frames -> speech segments (webrtcvad) [pure-ish]
    session.py       # build_utterance(text, confidence, source) -> UtteranceIn
  voice/
    __init__.py
    client.py        # ServiceClient: POST /utterance to io serve
    loop.py          # VoiceLoop: capture -> transcribe -> client -> speak; push-to-talk + passive
  doctor.py          # run_checks(config) -> list[Check]; formatting
  cli.py             # `io listen`, real `io doctor`
tests/
  test_speak_text.py            # flatten_markdown
  test_speak_piper.py           # @voice: real synth; + Fake contract
  test_transcribe_whisper.py    # @voice: fixture WAV; + Fake contract
  test_capture_vad.py           # segmentation over a synthetic frame stream
  test_capture_session.py       # build_utterance
  test_voice_loop.py            # VoiceLoop with fakes end-to-end
  test_doctor.py                # run_checks with monkeypatched probes
  test_cli_listen.py            # command registered / wiring
  fixtures/audio/hello.wav      # ~1s "hello" (committed; used by @voice test)
```

---

## Task 1: `[voice]` + `[capture]` config

**Files:**
- Modify: `io_assistant/config.py`, `config.toml`, `tests/conftest.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `VoiceConfig` (pydantic): `tts_voice: str = "en_US-amy-medium"`,
    `voices_dir: str = "~/.local/share/io/piper"`, `speak_in_app: bool = False`,
    `piper_bin: str | None = None` (None → try the `piper-tts` package, then a
    `piper` on `PATH`).
  - `CaptureConfig` (pydantic): `hotkey: str = "<ctrl>+<alt>+space"`,
    `passive: bool = False`, `sample_rate: int = 16000`,
    `vad_aggressiveness: int = 2` (0–3).
  - `Config.voice: VoiceConfig = VoiceConfig()`,
    `Config.capture: CaptureConfig = CaptureConfig()` — both optional in TOML.
  - `VoiceConfig.resolved_voice_path` — `Path(expanduser(voices_dir)) /
    f"{tts_voice}.onnx"`.
  - `whisper_model_for(profile: str) -> str` in `io_assistant/config.py`:
    `"light"→"base"`, `"quality"→"small"`, default `"base"`.

- [ ] **Step 1: Write the failing test** — `tests/test_config.py` (append)

```python
def test_voice_and_capture_defaults(tmp_path):
    p = write_toml(tmp_path, """
        database_url = "postgresql+psycopg://u:p@localhost/db"
        embedding_dim = 768
        [backend]
        provider = "local"
        profile = "light"
        anthropic_model = "claude-haiku-4-5"
        ollama_url = "http://localhost:11434"
        ollama_keep_alive = "30s"
        instruct_model = "llama3.2:3b"
        embed_model = "nomic-embed-text"
        num_thread = 0
        [resolver]
        fuzzy_threshold = 92
        vector_similarity_threshold = 0.85
        confidence_gate_threshold = 0.6
    """)
    cfg = load_config(p)
    assert cfg.voice.tts_voice == "en_US-amy-medium"
    assert cfg.capture.passive is False
    from io_assistant.config import whisper_model_for
    assert whisper_model_for("light") == "base"
    assert whisper_model_for("quality") == "small"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_config.py::test_voice_and_capture_defaults -v`
Expected: FAIL — `Config` has no `voice`.

- [ ] **Step 3: Implement** — `io_assistant/config.py`

```python
from os.path import expanduser
from pathlib import Path


class VoiceConfig(BaseModel):
    tts_voice: str = "en_US-amy-medium"
    voices_dir: str = "~/.local/share/io/piper"
    speak_in_app: bool = False
    piper_bin: str | None = None

    @property
    def resolved_voice_path(self) -> Path:
        return Path(expanduser(self.voices_dir)) / f"{self.tts_voice}.onnx"


class CaptureConfig(BaseModel):
    hotkey: str = "<ctrl>+<alt>+space"
    passive: bool = False
    sample_rate: int = 16000
    vad_aggressiveness: int = 2


class Config(BaseModel):
    database_url: str
    embedding_dim: int
    backend: BackendConfig
    resolver: ResolverConfig
    service: ServiceConfig = ServiceConfig()
    voice: VoiceConfig = VoiceConfig()
    capture: CaptureConfig = CaptureConfig()


_WHISPER_BY_PROFILE = {"light": "base", "quality": "small"}


def whisper_model_for(profile: str) -> str:
    return _WHISPER_BY_PROFILE.get(profile, "base")
```

- [ ] **Step 4: Update `config.toml`** — add:
```toml
[voice]
tts_voice = "en_US-amy-medium"
voices_dir = "~/.local/share/io/piper"
speak_in_app = false

[capture]
hotkey = "<ctrl>+<alt>+space"
passive = false
```

- [ ] **Step 5: Update the `config` fixture** — `tests/conftest.py`

Import `VoiceConfig, CaptureConfig` and add `voice=VoiceConfig(),
capture=CaptureConfig()` to the fixture's `Config(...)`.

- [ ] **Step 6: Run**

Run: `uv run pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add io_assistant/config.py config.toml tests/
git commit -m "feat: [voice] and [capture] config; whisper_model_for(profile)"
```

---

## Task 2: `speak/` — `flatten_markdown`, `Speaker` protocol, `PiperSpeaker`, `FakeSpeaker`

**Files:**
- Create: `io_assistant/speak/__init__.py`, `interface.py`, `text.py`, `piper.py`
- Test: `tests/test_speak_text.py`, `tests/test_speak_piper.py`,
  `tests/conftest.py` (`FakeSpeaker`)

**Interfaces:**
- Produces:
  - `io_assistant.speak.text.flatten_markdown(s: str) -> str` — pure. Removes
    heading `#`s, list markers (`- `, `* `, `1. `), emphasis (`**`, `*`, `` ` ``),
    link syntax (`[t](u)` → `t`); replaces a fenced ```` ```mermaid ```` block
    (or any fenced block) with `"a diagram"` / `"a code block"`; collapses blank
    runs; trims. Deterministic, no I/O.
  - `io_assistant.speak.interface.Speaker` (Protocol):
    `say(self, text: str) -> None` (synthesize + play, blocking);
    `synthesize(self, text: str) -> bytes` (WAV bytes, no playback).
    `SpeakError(Exception)`.
  - `io_assistant.speak.piper.PiperSpeaker(config: Config)` implementing
    `Speaker`:
    - resolves the voice: `config.voice.resolved_voice_path` must exist, else
      `SpeakError` with a message naming the file and the download command.
    - `synthesize`: flattens via `flatten_markdown`, runs Piper (the `piper-tts`
      Python API if importable, else `subprocess` the `piper` binary
      `--model <path> --output_file -`), returns WAV bytes.
    - `say`: `synthesize` then play through `sounddevice` (lazy import;
      `SpeakError` if no output device).
  - `FakeSpeaker` (conftest): records `.said: list[str]` and
    `.synth_calls: list[str]`; `synthesize` returns a 44-byte WAV header stub.

- [ ] **Step 1: Write the failing test** — `tests/test_speak_text.py`

```python
from io_assistant.speak.text import flatten_markdown


def test_strips_markdown_to_prose():
    md = "# Today\n\n- **finish** the `deck`\n- email [Sam](mailto:s@x.com)\n"
    out = flatten_markdown(md)
    assert "#" not in out and "*" not in out and "`" not in out
    assert "finish the deck" in out
    assert "Sam" in out and "mailto" not in out


def test_fenced_blocks_become_words():
    md = "Here:\n```mermaid\ngraph TD; A-->B\n```\nand\n```\nx=1\n```"
    out = flatten_markdown(md)
    assert "a diagram" in out
    assert "graph TD" not in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_speak_text.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `io_assistant/speak/text.py`**

```python
from __future__ import annotations

import re

_FENCE = re.compile(r"```(\w*)\n.*?```", re.S)


def flatten_markdown(s: str) -> str:
    def _fence(m: re.Match) -> str:
        return "a diagram" if m.group(1) == "mermaid" else "a code block"

    s = _FENCE.sub(_fence, s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"\*([^*]+)\*", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"^\s*#{1,6}\s*", "", s, flags=re.M)
    s = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", s, flags=re.M)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()
```

- [ ] **Step 4: Implement `io_assistant/speak/interface.py`**

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable


class SpeakError(Exception):
    pass


@runtime_checkable
class Speaker(Protocol):
    def say(self, text: str) -> None: ...
    def synthesize(self, text: str) -> bytes: ...
```

- [ ] **Step 5: Implement `io_assistant/speak/piper.py`**

```python
from __future__ import annotations

import io
import shutil
import subprocess
import wave

from io_assistant.config import Config
from io_assistant.speak.interface import SpeakError
from io_assistant.speak.text import flatten_markdown


class PiperSpeaker:
    def __init__(self, config: Config):
        self._cfg = config.voice
        self._voice_path = config.voice.resolved_voice_path

    def _check_voice(self) -> None:
        if not self._voice_path.exists():
            raise SpeakError(
                f"Piper voice not found: {self._voice_path}\n"
                f"Download it, e.g.: python -m piper.download_voices "
                f"{self._cfg.tts_voice} --data-dir {self._voice_path.parent}"
            )

    def synthesize(self, text: str) -> bytes:
        self._check_voice()
        prose = flatten_markdown(text) or "Nothing to say."
        try:
            from piper import PiperVoice  # type: ignore

            voice = PiperVoice.load(str(self._voice_path))
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                voice.synthesize(prose, wf)
            return buf.getvalue()
        except ImportError:
            pass
        binary = self._cfg.piper_bin or shutil.which("piper")
        if not binary:
            raise SpeakError(
                "Piper not available: install `piper-tts` or put a `piper` "
                "binary on PATH (or set [voice].piper_bin)."
            )
        proc = subprocess.run(
            [binary, "--model", str(self._voice_path), "--output_file", "-"],
            input=prose.encode(), capture_output=True,
        )
        if proc.returncode != 0:
            raise SpeakError(f"piper failed: {proc.stderr.decode()[:200]}")
        return proc.stdout

    def say(self, text: str) -> None:
        data = self.synthesize(text)
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as e:
            raise SpeakError(f"audio playback unavailable: {e}") from e
        with wave.open(io.BytesIO(data), "rb") as wf:
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
        audio = np.frombuffer(frames, dtype=np.int16)
        sd.play(audio, rate)
        sd.wait()
```

- [ ] **Step 6: Add `FakeSpeaker` to `tests/conftest.py`**

```python
class FakeSpeaker:
    def __init__(self):
        self.said: list[str] = []
        self.synth_calls: list[str] = []

    def say(self, text: str) -> None:
        self.said.append(text)

    def synthesize(self, text: str) -> bytes:
        self.synth_calls.append(text)
        return b"RIFF\x00\x00\x00\x00WAVEfmt "

@pytest.fixture
def fake_speaker():
    return FakeSpeaker()
```

- [ ] **Step 7: Write `tests/test_speak_piper.py`** (contract + opt-in real)

```python
import os
import pytest

from io_assistant.speak.interface import Speaker, SpeakError
from io_assistant.speak.piper import PiperSpeaker


def test_fake_speaker_satisfies_protocol(fake_speaker):
    assert isinstance(fake_speaker, Speaker)


def test_piper_missing_voice_raises(config, tmp_path):
    config.voice.voices_dir = str(tmp_path)  # empty -> no voice file
    with pytest.raises(SpeakError, match="voice not found"):
        PiperSpeaker(config).synthesize("hello")


@pytest.mark.voice
@pytest.mark.skipif(os.environ.get("IO_VOICE_TESTS") != "1", reason="opt-in")
def test_piper_real_synthesis(config):
    data = PiperSpeaker(config).synthesize("Hello from eye oh.")
    assert data[:4] == b"RIFF" and len(data) > 1000
```

Add the `voice` marker to `pyproject.toml` `[tool.pytest.ini_options].markers`:
`"voice: requires local Whisper/Piper models (set IO_VOICE_TESTS=1)"`.

- [ ] **Step 8: Run**

Run: `uv run pytest tests/test_speak_text.py tests/test_speak_piper.py -q`
Expected: PASS (real-synthesis test skipped).

- [ ] **Step 9: Commit**

```bash
git add io_assistant/speak/ tests/test_speak_text.py tests/test_speak_piper.py tests/conftest.py pyproject.toml
git commit -m "feat: speak/ — flatten_markdown + Speaker protocol + PiperSpeaker/FakeSpeaker"
```

---

## Task 3: `transcribe/` — `Transcriber` protocol, `WhisperTranscriber`, `FakeTranscriber`

**Files:**
- Create: `io_assistant/transcribe/__init__.py`, `interface.py`, `whisper.py`
- Test: `tests/test_transcribe_whisper.py`, `tests/conftest.py`
  (`FakeTranscriber`), `tests/fixtures/audio/hello.wav`

**Interfaces:**
- Produces:
  - `io_assistant.transcribe.interface`:
    - `Transcript` (dataclass): `text: str`, `confidence: float | None`.
    - `Transcriber` (Protocol): `transcribe(self, wav_path: str) -> Transcript`.
    - `TranscribeError(Exception)`.
  - `io_assistant.transcribe.whisper.WhisperTranscriber(config: Config)`:
    - model size from `whisper_model_for(config.backend.profile)`; `device`
      `"cuda"` if available else `"cpu"`; `compute_type` `"int8"`.
    - lazy `from faster_whisper import WhisperModel`; missing package →
      `TranscribeError` naming the install.
    - `transcribe`: runs the model, joins segments, sets `confidence` from the
      mean segment `avg_logprob` mapped to `[0,1]` (`exp(avg_logprob)` clamped).
  - `FakeTranscriber` (conftest): `set_text(s)` / `set_confidence(c)`;
    `transcribe` returns the configured `Transcript` and records `.calls`.

- [ ] **Step 1: Create the fixture** — a ~1s mono 16 kHz WAV saying "hello".
  Generate it deterministically so it can be committed:
  `uv run python -c "import wave,struct,math; ..."` — write
  `tests/fixtures/audio/hello.wav` as 1s of a 220 Hz tone (the `@voice` test
  only checks it returns *some* text without error; a tone is enough to exercise
  the pipeline, and a real "hello" clip can replace it later). Document this in
  the test.

- [ ] **Step 2: Write the failing test** — `tests/test_transcribe_whisper.py`

```python
import os
import pytest

from io_assistant.transcribe.interface import Transcriber, Transcript


def test_fake_transcriber_satisfies_protocol(fake_transcriber):
    assert isinstance(fake_transcriber, Transcriber)


def test_fake_transcriber_returns_configured(fake_transcriber):
    fake_transcriber.set_text("buy milk")
    fake_transcriber.set_confidence(0.9)
    t = fake_transcriber.transcribe("ignored.wav")
    assert isinstance(t, Transcript)
    assert t.text == "buy milk" and t.confidence == 0.9


@pytest.mark.voice
@pytest.mark.skipif(os.environ.get("IO_VOICE_TESTS") != "1", reason="opt-in")
def test_whisper_real_transcription(config):
    from pathlib import Path
    from io_assistant.transcribe.whisper import WhisperTranscriber
    wav = Path(__file__).parent / "fixtures" / "audio" / "hello.wav"
    t = WhisperTranscriber(config).transcribe(str(wav))
    assert isinstance(t.text, str)
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/test_transcribe_whisper.py -q`
Expected: FAIL — `ModuleNotFoundError` / no `fake_transcriber`.

- [ ] **Step 4: Implement `io_assistant/transcribe/interface.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class TranscribeError(Exception):
    pass


@dataclass
class Transcript:
    text: str
    confidence: float | None = None


@runtime_checkable
class Transcriber(Protocol):
    def transcribe(self, wav_path: str) -> Transcript: ...
```

- [ ] **Step 5: Implement `io_assistant/transcribe/whisper.py`**

```python
from __future__ import annotations

import math

from io_assistant.config import Config, whisper_model_for
from io_assistant.transcribe.interface import Transcript, TranscribeError


class WhisperTranscriber:
    def __init__(self, config: Config):
        self._size = whisper_model_for(config.backend.profile)
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise TranscribeError(
                    "faster-whisper not installed (`uv add faster-whisper`)."
                ) from e
            device, compute = _pick_device()
            self._model = WhisperModel(self._size, device=device, compute_type=compute)
        return self._model

    def transcribe(self, wav_path: str) -> Transcript:
        model = self._load()
        try:
            segments, _info = model.transcribe(wav_path, vad_filter=True)
            segs = list(segments)
        except Exception as e:  # noqa: BLE001
            raise TranscribeError(str(e)) from e
        text = " ".join(s.text.strip() for s in segs).strip()
        if segs:
            avg = sum(getattr(s, "avg_logprob", -1.0) for s in segs) / len(segs)
            conf = max(0.0, min(1.0, math.exp(avg)))
        else:
            conf = None
        return Transcript(text=text, confidence=conf)


def _pick_device() -> tuple[str, str]:
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda", "int8_float16"
    except Exception:
        pass
    return "cpu", "int8"
```

- [ ] **Step 6: Add `FakeTranscriber` to `tests/conftest.py`**

```python
from io_assistant.transcribe.interface import Transcript

class FakeTranscriber:
    def __init__(self):
        self._text = ""
        self._conf = None
        self.calls: list[str] = []
    def set_text(self, s): self._text = s
    def set_confidence(self, c): self._conf = c
    def transcribe(self, wav_path: str) -> Transcript:
        self.calls.append(wav_path)
        return Transcript(text=self._text, confidence=self._conf)

@pytest.fixture
def fake_transcriber():
    return FakeTranscriber()
```

- [ ] **Step 7: Run**

Run: `uv run pytest tests/test_transcribe_whisper.py -q`
Expected: PASS (real test skipped).

- [ ] **Step 8: Commit**

```bash
git add io_assistant/transcribe/ tests/test_transcribe_whisper.py tests/fixtures/audio/ tests/conftest.py
git commit -m "feat: transcribe/ — Transcriber protocol + WhisperTranscriber/FakeTranscriber"
```

---

## Task 4: `capture/` — VAD segmentation + utterance assembly

**Files:**
- Create: `io_assistant/capture/__init__.py`, `vad.py`, `session.py`, `audio.py`,
  `hotkey.py`
- Test: `tests/test_capture_vad.py`, `tests/test_capture_session.py`

**Interfaces:**
- Produces:
  - `io_assistant.capture.vad.segment_stream(frames: Iterable[bytes], *, rate: int, aggressiveness: int, frame_ms: int = 30, min_speech_ms: int = 300, max_silence_ms: int = 700) -> Iterator[bytes]`
    — a generator: feeds 30 ms PCM16 frames through `webrtcvad`, yields one
    concatenated `bytes` blob per detected speech segment (speech run longer
    than `min_speech_ms`, ended by `max_silence_ms` of silence). `webrtcvad` is
    lazy-imported; if absent, a `TranscribeError`-free fallback treats every
    frame whose RMS exceeds a threshold as speech (documented as coarse).
  - `io_assistant.capture.session.build_utterance(text: str, confidence: float | None, source: str = "voice") -> io_assistant.service.schemas.UtteranceIn`
    — trims text; raises `ValueError` on empty text.
  - `io_assistant.capture.audio.record_fixed(seconds: float, *, rate: int) -> bytes`
    and `record_until(stop: threading.Event, *, rate: int) -> bytes` — thin
    `sounddevice` seams (not unit-tested; used by the loop, mocked there).
  - `io_assistant.capture.hotkey.push_to_talk(combo: str, on_press, on_release) -> "listener"`
    — thin `pynput` seam returning a started listener with `.stop()`.

- [ ] **Step 1: Write the failing tests**

`tests/test_capture_vad.py`:
```python
from io_assistant.capture.vad import segment_stream


def _frames(pattern, rate=16000, frame_ms=30):
    """pattern: list of ('speech'|'silence', ms). Speech = 0x40 bytes, silence = 0x00."""
    n = int(rate * frame_ms / 1000)
    out = []
    for kind, ms in pattern:
        for _ in range(ms // frame_ms):
            out.append((b"\x40\x10" * n) if kind == "speech" else (b"\x00\x00" * n))
    return out


def test_one_segment_between_silences():
    frames = _frames([("silence", 300), ("speech", 600), ("silence", 900),
                      ("speech", 450), ("silence", 300)])
    segs = list(segment_stream(frames, rate=16000, aggressiveness=0))
    assert len(segs) == 2
    assert all(isinstance(s, bytes) and len(s) > 0 for s in segs)


def test_short_blip_is_dropped():
    frames = _frames([("silence", 300), ("speech", 90), ("silence", 900)])
    assert list(segment_stream(frames, rate=16000, aggressiveness=0)) == []
```

`tests/test_capture_session.py`:
```python
import pytest
from io_assistant.capture.session import build_utterance
from io_assistant.service.schemas import UtteranceIn


def test_build_utterance():
    u = build_utterance("  buy milk \n", 0.8)
    assert isinstance(u, UtteranceIn)
    assert u.text == "buy milk" and u.source == "voice"


def test_build_utterance_rejects_empty():
    with pytest.raises(ValueError):
        build_utterance("   ", None)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_capture_vad.py tests/test_capture_session.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `io_assistant/capture/vad.py`**

```python
from __future__ import annotations

from collections.abc import Iterable, Iterator


def _rms_speech(frame: bytes, threshold: int = 500) -> bool:
    import array
    a = array.array("h")
    a.frombytes(frame)
    if not a:
        return False
    return (sum(x * x for x in a) / len(a)) ** 0.5 > threshold


def segment_stream(
    frames: Iterable[bytes],
    *,
    rate: int,
    aggressiveness: int,
    frame_ms: int = 30,
    min_speech_ms: int = 300,
    max_silence_ms: int = 700,
) -> Iterator[bytes]:
    try:
        import webrtcvad
        vad = webrtcvad.Vad(aggressiveness)
        is_speech = lambda f: vad.is_speech(f, rate)  # noqa: E731
    except Exception:
        is_speech = _rms_speech

    buf: list[bytes] = []
    speech_ms = 0
    silence_ms = 0
    in_speech = False
    for frame in frames:
        speaking = is_speech(frame)
        if speaking:
            buf.append(frame)
            speech_ms += frame_ms
            silence_ms = 0
            in_speech = in_speech or speech_ms >= min_speech_ms
        elif in_speech:
            buf.append(frame)
            silence_ms += frame_ms
            if silence_ms >= max_silence_ms:
                yield b"".join(buf)
                buf, speech_ms, silence_ms, in_speech = [], 0, 0, False
        else:
            buf, speech_ms = [], 0
    if in_speech and buf:
        yield b"".join(buf)
```

- [ ] **Step 4: Implement `io_assistant/capture/session.py`**

```python
from __future__ import annotations

from io_assistant.service.schemas import UtteranceIn


def build_utterance(text: str, confidence: float | None, source: str = "voice") -> UtteranceIn:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("empty transcript")
    return UtteranceIn(text=cleaned, source=source)
```

- [ ] **Step 5: Implement `audio.py` and `hotkey.py`** (thin seams)

```python
# audio.py
from __future__ import annotations
import threading


def record_fixed(seconds: float, *, rate: int) -> bytes:
    import numpy as np, sounddevice as sd
    frames = sd.rec(int(seconds * rate), samplerate=rate, channels=1, dtype="int16")
    sd.wait()
    return np.asarray(frames, dtype="int16").tobytes()


def record_until(stop: threading.Event, *, rate: int) -> bytes:
    import numpy as np, sounddevice as sd
    chunks: list[bytes] = []
    with sd.InputStream(samplerate=rate, channels=1, dtype="int16") as stream:
        while not stop.is_set():
            data, _ = stream.read(int(rate * 0.1))
            chunks.append(np.asarray(data, dtype="int16").tobytes())
    return b"".join(chunks)
```
```python
# hotkey.py
from __future__ import annotations


def push_to_talk(combo: str, on_press, on_release):
    from pynput import keyboard
    listener = keyboard.GlobalHotKeys({combo: on_press})
    listener.start()
    return listener
```
(These have no unit test — the loop test mocks them.)

- [ ] **Step 6: Run**

Run: `uv run pytest tests/test_capture_vad.py tests/test_capture_session.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add io_assistant/capture/ tests/test_capture_vad.py tests/test_capture_session.py
git commit -m "feat: capture/ — VAD segmentation + build_utterance + audio/hotkey seams"
```

---

## Task 5: `voice/` — service client + `VoiceLoop` + `io listen`

**Files:**
- Create: `io_assistant/voice/__init__.py`, `client.py`, `loop.py`
- Modify: `io_assistant/cli.py`
- Test: `tests/test_voice_loop.py`, `tests/test_cli_listen.py`

**Interfaces:**
- Produces:
  - `io_assistant.voice.client.ServiceClient(base_url: str, *, http=None)` —
    `send(self, u: UtteranceIn) -> UtteranceOut` (POST `/utterance`),
    `health(self) -> bool`. `http` injectable for tests (defaults to a
    module-level `httpx` call).
  - `io_assistant.voice.loop.VoiceLoop(config, *, transcriber, speaker, client, recorder=None)`
    — `handle_wav(self, wav_path: str) -> str`: transcribe → `build_utterance`
    → `client.send` → `speaker.say(reply.message)` → return the message.
    Empty transcript → speaks nothing, returns `""`. A `SpeakError` is caught,
    logged as a one-line warning, and the text still returns (spec §6.1
    "degrades to text-only, not fatal").
    - `run_push_to_talk(self)` — wires `capture.hotkey.push_to_talk` +
      `capture.audio.record_until`; on release, writes the PCM to a temp WAV and
      calls `handle_wav`. Loops until Ctrl-C.
    - `run_passive(self)` — opens the mic stream, feeds
      `capture.vad.segment_stream`, writes each segment to a temp WAV, calls
      `handle_wav`.
  - `io listen` (Typer) — `--passive/--push` (default from
    `config.capture.passive`); builds real `WhisperTranscriber` + `PiperSpeaker`
    + `ServiceClient(f"http://{host}:{port}")`; checks `client.health()` first
    (tells the user to start `io serve`); runs the chosen loop.

- [ ] **Step 1: Write the failing test** — `tests/test_voice_loop.py`

```python
from io_assistant.voice.loop import VoiceLoop
from io_assistant.service.schemas import UtteranceOut


class _Client:
    def __init__(self, out): self.out = out; self.sent = []
    def send(self, u): self.sent.append(u); return self.out
    def health(self): return True


def test_handle_wav_speaks_reply(config, fake_transcriber, fake_speaker):
    fake_transcriber.set_text("what work do I have today")
    fake_transcriber.set_confidence(0.9)
    client = _Client(UtteranceOut(intent="query", message="Two tasks are open."))
    loop = VoiceLoop(config, transcriber=fake_transcriber, speaker=fake_speaker, client=client)
    msg = loop.handle_wav("x.wav")
    assert msg == "Two tasks are open."
    assert fake_speaker.said == ["Two tasks are open."]
    assert client.sent[0].text == "what work do I have today"
    assert client.sent[0].source == "voice"


def test_handle_wav_empty_transcript_is_silent(config, fake_transcriber, fake_speaker):
    fake_transcriber.set_text("   ")
    client = _Client(UtteranceOut(intent="unknown", message="?"))
    loop = VoiceLoop(config, transcriber=fake_transcriber, speaker=fake_speaker, client=client)
    assert loop.handle_wav("x.wav") == ""
    assert fake_speaker.said == [] and client.sent == []


def test_speak_failure_is_not_fatal(config, fake_transcriber):
    from io_assistant.speak.interface import SpeakError
    fake_transcriber.set_text("hello")

    class BadSpeaker:
        def say(self, t): raise SpeakError("no audio device")
        def synthesize(self, t): return b""

    client = _Client(UtteranceOut(intent="store", message="Stored."))
    loop = VoiceLoop(config, transcriber=fake_transcriber, speaker=BadSpeaker(), client=client)
    assert loop.handle_wav("x.wav") == "Stored."
```

`tests/test_cli_listen.py`:
```python
from typer.testing import CliRunner
from io_assistant.cli import app


def test_listen_command_registered():
    assert CliRunner().invoke(app, ["listen", "--help"]).exit_code == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_voice_loop.py tests/test_cli_listen.py -q`
Expected: FAIL — no `io_assistant.voice`.

- [ ] **Step 3: Implement `io_assistant/voice/client.py`**

```python
from __future__ import annotations

import httpx

from io_assistant.service.schemas import UtteranceIn, UtteranceOut


class ServiceClient:
    def __init__(self, base_url: str, *, http=None):
        self._base = base_url.rstrip("/")
        self._http = http or httpx

    def health(self) -> bool:
        try:
            return bool(self._http.get(f"{self._base}/health", timeout=2).json().get("ok"))
        except Exception:
            return False

    def send(self, u: UtteranceIn) -> UtteranceOut:
        r = self._http.post(f"{self._base}/utterance", json=u.model_dump(), timeout=120)
        r.raise_for_status()
        return UtteranceOut.model_validate(r.json())
```

- [ ] **Step 4: Implement `io_assistant/voice/loop.py`**

```python
from __future__ import annotations

import sys
import tempfile
import wave

from io_assistant.capture.session import build_utterance
from io_assistant.speak.interface import SpeakError


class VoiceLoop:
    def __init__(self, config, *, transcriber, speaker, client, recorder=None):
        self._cfg = config
        self._t = transcriber
        self._s = speaker
        self._client = client
        self._rate = config.capture.sample_rate

    def handle_wav(self, wav_path: str) -> str:
        tr = self._t.transcribe(wav_path)
        try:
            u = build_utterance(tr.text, tr.confidence)
        except ValueError:
            return ""
        reply = self._client.send(u)
        try:
            self._s.say(reply.message)
        except SpeakError as e:
            print(f"[voice] speech output unavailable: {e}", file=sys.stderr)
        return reply.message

    def _pcm_to_wav(self, pcm: bytes) -> str:
        path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._rate)
            wf.writeframes(pcm)
        return path

    def run_push_to_talk(self) -> None:
        import threading

        from io_assistant.capture.audio import record_until
        from io_assistant.capture.hotkey import push_to_talk

        print("Hold the hotkey and speak. Ctrl-C to quit.")
        stop = threading.Event()
        state = {"rec": None}

        def on_press():
            if state["rec"] is None:
                stop.clear()
                state["rec"] = threading.Thread(
                    target=lambda: state.__setitem__("pcm", record_until(stop, rate=self._rate))
                )
                state["rec"].start()

        def on_release():
            if state["rec"] is not None:
                stop.set()
                state["rec"].join()
                state["rec"] = None
                self.handle_wav(self._pcm_to_wav(state.pop("pcm", b"")))

        listener = push_to_talk(self._cfg.capture.hotkey, on_press, on_release)
        try:
            listener.join()
        except KeyboardInterrupt:
            listener.stop()

    def run_passive(self) -> None:
        import numpy as np
        import sounddevice as sd

        from io_assistant.capture.vad import segment_stream

        print("Passive mode — everything you say is routed. Ctrl-C to quit.")
        frame = int(self._rate * 0.03)

        def frames():
            with sd.InputStream(samplerate=self._rate, channels=1, dtype="int16") as st:
                while True:
                    data, _ = st.read(frame)
                    yield np.asarray(data, dtype="int16").tobytes()

        try:
            for seg in segment_stream(
                frames(), rate=self._rate,
                aggressiveness=self._cfg.capture.vad_aggressiveness,
            ):
                self.handle_wav(self._pcm_to_wav(seg))
        except KeyboardInterrupt:
            return
```

- [ ] **Step 5: Add `io listen`** — `io_assistant/cli.py`

```python
@app.command()
def listen(passive: bool = typer.Option(None, help="hands-free VAD mode")) -> None:
    """Voice: speak to io, hear the answer."""
    from io_assistant.speak.piper import PiperSpeaker
    from io_assistant.transcribe.whisper import WhisperTranscriber
    from io_assistant.voice.client import ServiceClient
    from io_assistant.voice.loop import VoiceLoop

    config = load_config()
    base = f"http://{config.service.host}:{config.service.port}"
    client = ServiceClient(base)
    if not client.health():
        print(f"io service not reachable at {base} — run `io serve` first.")
        raise typer.Exit(1)
    loop = VoiceLoop(config, transcriber=WhisperTranscriber(config),
                     speaker=PiperSpeaker(config), client=client)
    use_passive = config.capture.passive if passive is None else passive
    (loop.run_passive if use_passive else loop.run_push_to_talk)()
```

- [ ] **Step 6: Run**

Run: `uv run pytest tests/test_voice_loop.py tests/test_cli_listen.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add io_assistant/voice/ io_assistant/cli.py tests/test_voice_loop.py tests/test_cli_listen.py
git commit -m "feat: voice/ — ServiceClient + VoiceLoop (push-to-talk / passive) + io listen"
```

---

## Task 6: real `io doctor`

**Files:**
- Create: `io_assistant/doctor.py`
- Modify: `io_assistant/cli.py`
- Test: `tests/test_doctor.py`

**Interfaces:**
- Produces:
  - `io_assistant.doctor.Check` (dataclass): `name: str`, `ok: bool`,
    `detail: str`.
  - `io_assistant.doctor.run_checks(config: Config) -> list[Check]` — each check
    is isolated and never raises:
    1. **PostgreSQL** — `SELECT 1` on `config.database_url`.
    2. **pgvector** — `SELECT 1 FROM pg_extension WHERE extname='vector'`.
    3. **Backend** — `provider == "local"`: Ollama `/api/tags` reachable and
       `config.backend.instruct_model` present; `"anthropic"`/`"hybrid"`:
       `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` set.
    4. **Embeddings** — Ollama `/api/tags` lists `config.backend.embed_model`.
    5. **Whisper** — `faster_whisper` importable.
    6. **Piper** — `piper` package importable or a `piper` binary on PATH, AND
       `config.voice.resolved_voice_path` exists.
    7. **VRAM** — if `torch.cuda` present, free VRAM vs the profile's
       mid-request need (§13.2: light ≈ 4 GB, quality ≈ 5.5 GB); a warn, not a
       fail, when low. Skipped (ok, "no CUDA") when torch/CUDA absent.
  - `io_assistant.doctor.format_report(checks) -> str` — aligned `OK/FAIL/WARN`
    lines.
  - `io doctor` (Typer) — prints `format_report(run_checks(load_config()))`;
    exit code `1` if any check `not ok`.

- [ ] **Step 1: Write the failing test** — `tests/test_doctor.py`

```python
from io_assistant.doctor import run_checks, format_report, Check


def test_run_checks_returns_named_checks(config, monkeypatch):
    import io_assistant.doctor as d
    monkeypatch.setattr(d, "_check_postgres", lambda c: Check("PostgreSQL", True, "ok"))
    monkeypatch.setattr(d, "_check_pgvector", lambda c: Check("pgvector", True, "ok"))
    monkeypatch.setattr(d, "_check_backend", lambda c: Check("backend", True, "local"))
    monkeypatch.setattr(d, "_check_embeddings", lambda c: Check("embeddings", True, "ok"))
    monkeypatch.setattr(d, "_check_whisper", lambda c: Check("Whisper", False, "not installed"))
    monkeypatch.setattr(d, "_check_piper", lambda c: Check("Piper", False, "no voice model"))
    monkeypatch.setattr(d, "_check_vram", lambda c: Check("VRAM", True, "no CUDA"))
    checks = run_checks(config)
    names = [c.name for c in checks]
    assert "PostgreSQL" in names and "Piper" in names
    report = format_report(checks)
    assert "FAIL" in report and "Whisper" in report


def test_doctor_cli_exit_code(monkeypatch):
    from typer.testing import CliRunner
    import io_assistant.cli as cli
    import io_assistant.doctor as d
    monkeypatch.setattr(d, "run_checks", lambda c: [Check("x", False, "bad")])
    monkeypatch.setattr(cli, "load_config", lambda: object())
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert r.exit_code == 1 and "FAIL" in r.output
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_doctor.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `io_assistant/doctor.py`** — one function per check,
  each wrapped so it returns a `Check` and never raises. `run_checks` calls them
  in order. Use `httpx` for Ollama, `sqlalchemy.create_engine` +
  `text("SELECT 1")` for Postgres, `importlib.util.find_spec` for the Python
  packages, `shutil.which` for the binary, `os.environ` for the credential.
  `format_report` pads `name` to the longest and prefixes
  `OK  ` / `FAIL` / `WARN`.

  (Full implementation — each `_check_*` follows this shape:)
```python
def _check_postgres(config) -> Check:
    from sqlalchemy import create_engine, text
    try:
        eng = create_engine(config.database_url)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return Check("PostgreSQL", True, config.database_url.split("@")[-1])
    except Exception as e:
        return Check("PostgreSQL", False, str(e)[:120])
```

- [ ] **Step 4: Replace `io doctor`** — `io_assistant/cli.py`

```python
@app.command()
def doctor() -> None:
    """Check the local stack (Postgres, pgvector, models, Whisper, Piper)."""
    from io_assistant.doctor import format_report, run_checks
    checks = run_checks(load_config())
    print(format_report(checks))
    raise typer.Exit(0 if all(c.ok for c in checks) else 1)
```

- [ ] **Step 5: Run**

Run: `uv run pytest tests/test_doctor.py -q`
Expected: PASS.

- [ ] **Step 6: Manual run** (record output in the commit)

Run: `uv run io doctor` — expect PostgreSQL/pgvector OK (DB up), backend per
config, Whisper/Piper likely FAIL until models are installed. Exit 1 is correct
then.

- [ ] **Step 7: Commit**

```bash
git add io_assistant/doctor.py io_assistant/cli.py tests/test_doctor.py
git commit -m "feat: io doctor — Postgres/pgvector/backend/embeddings/Whisper/Piper/VRAM checks"
```

---

## Task 7: docs, run-local, state

**Files:**
- Modify: `.claude/knowledge/local-stack.md`, `.claude/skills/run-local.md`,
  `.claude/state/*`, `.env.example`
- Test: none (docs).

- [ ] **Step 1: `.claude/knowledge/local-stack.md`** — add a "Voice" section:
  Whisper model per profile (`whisper_model_for`), Piper voice download
  (`python -m piper.download_voices en_US-amy-medium --data-dir <voices_dir>`),
  the `[voice]`/`[capture]` config, `io listen` (push-to-talk default, `--passive`),
  and that a missing model degrades to text-only.

- [ ] **Step 2: `.claude/skills/run-local.md`** — append the voice setup steps
  and `uv run io doctor` as the go/no-go check.

- [ ] **Step 3: `.env.example`** — note `IO_VOICE_TESTS=1` for the opt-in
  Whisper/Piper tests.

- [ ] **Step 4: Full suite**

Run: `uv run pytest -q`
Expected: PASS (voice-marked tests skipped without `IO_VOICE_TESTS=1`).
Confirm `tests/test_e2e_store.py`'s socket guard still passes — the voice client
only talks to `127.0.0.1`.

- [ ] **Step 5: Update state** — move Plan 4 from `backlog.md` to `completed.md`
  (dated); note what still needs a machine with a mic + GPU + downloaded models
  to verify end-to-end (`io listen` full loop, real transcription accuracy,
  hotkey capture, playback).

- [ ] **Step 6: Commit**

```bash
git add .claude/ .env.example
git commit -m "docs: voice setup in local-stack + run-local; Plan 4 complete"
```

---

## Self-Review

**Spec coverage:**
- §6.1 spoken output (Piper, local, female default, markdown flattened, speaks
  the gate prompt, degrades gracefully, not fatal) → Tasks 2 (`flatten_markdown`,
  `PiperSpeaker`) + 5 (`VoiceLoop.handle_wav` speaks `reply.message`, catches
  `SpeakError`).
- §6 push-to-talk hotkey → Task 4 (`hotkey.py`) + Task 5 (`run_push_to_talk`).
- §6 typed fallback → already shipped (`io repl`, service `POST /utterance`).
- §6 passive mode behind a config flag → Task 1 (`capture.passive`) + Task 4
  (`segment_stream`) + Task 5 (`run_passive`).
- §11 stage 16 Transcribe (`faster-whisper`, size from profile, fixed WAV test)
  → Task 3.
- §11 stage 17 Capture (`Utterance` assembly unit-tested; hotkey manual) → Task 4.
- §11 stage 18 Passive (VAD loop, segmentation unit-tested) → Task 4 + 5.
- §11 stage 19 `io doctor` (Postgres, pgvector, Ollama/Anthropic credential,
  models present, VRAM headroom) + Piper voice check → Task 6.
- §13.2 Whisper size per profile → `whisper_model_for` (Task 1).
- §13.3 no passive-mode model residency → passive path only touches VAD + Whisper;
  the instruct model still loads per utterance via the service.

**LLM-boundary check:** `Transcriber`, `Speaker`, `flatten_markdown`,
`segment_stream`, `build_utterance`, `doctor` — none import `Backend` or call a
model. The voice client sends text to the service; the service runs the one
pipeline.

**Local-first check:** Whisper + Piper are local; voice model files are
pre-downloaded (the code never fetches at runtime — `_check_voice` tells the
user the download command); the client's only network target is
`http://127.0.0.1:<port>`.

**Graceful degradation (no silent drops):** empty transcript → nothing spoken,
`""` returned, utterance not sent (it was noise). `SpeakError` → warning to
stderr, text still returned. Missing Whisper/Piper package → `TranscribeError` /
`SpeakError` with the install command; `io listen` surfaces it, `io doctor`
flags it.

**Placeholder scan:** Task 6 Step 3 gives the `_check_*` shape and one full
example rather than all seven bodies verbatim — each is the same 5-line
try/return-Check pattern against a named probe listed in the Interfaces block.
Every other step is literal code or a runnable command.

**Type consistency:**
- `Transcript(text, confidence)` — Task 3 def, Tasks 4/5 use.
- `Speaker.say/synthesize`, `SpeakError` — Tasks 2, 5, 6.
- `UtteranceIn` / `UtteranceOut` (from `io_assistant.service.schemas`, Plan 3) —
  `build_utterance` returns `UtteranceIn`; `ServiceClient.send` returns
  `UtteranceOut`; `VoiceLoop` reads `.message`.
- `Check(name, ok, detail)` — Task 6 def and test.
- `whisper_model_for(profile)` — Task 1 def, Task 3 use.
- config: `config.voice.*`, `config.capture.*`, `config.service.host/port`
  consistent across Tasks 1, 5, 6.

**Deferred (record in `backlog.md`):** token-streamed TTS (speak as the answer
streams — needs the Plan-3 `/ws` streaming follow-up); wake-word; barge-in
(stop speaking when the user starts talking); per-voice speed/pitch config;
choosing an input/output device in config.

---

## Execution Handoff

Plan complete. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between.
   Order: 1 → 2 → 3 → 4 → 5 (needs 2,3,4 + Plan-3 schemas) → 6 → 7.
2. **Inline Execution** — `superpowers:executing-plans`, batched with checkpoints.

**Note on verification:** Tasks 1, 2 (`flatten_markdown`), 4 (VAD, assembly),
5 (`VoiceLoop` with fakes), 6 (`io doctor` logic) are fully covered by normal
CI. The real Whisper/Piper adapters and the mic/hotkey/playback seams need a
machine with audio hardware, a GPU (or patience on CPU), and the downloaded
models — run `IO_VOICE_TESTS=1 uv run pytest -m voice` and `uv run io listen`
there.
