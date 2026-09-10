"""Local real-time speech-to-text — a rolling faster-whisper loop.

Fully offline. A `StreamSession` accumulates 16 kHz mono PCM16 and, every time
enough new audio has arrived, re-transcribes the un-committed tail. Segments
that end well before "now" are committed (they rarely change); the last ~2 s
stay provisional, so the visible text keeps correcting itself as you speak —
the same behaviour as the cloud path, without leaving the machine.

Best on a GPU (`large-v3-turbo` runs faster than real time on ~6 GB VRAM); on
CPU the partials lag. Gated by `voice.stt_provider = "whisper-stream"`.
"""
from __future__ import annotations

import threading

from io_assistant.config import Config
from io_assistant.transcribe.interface import TranscribeError

__all__ = ["StreamingWhisper", "StreamSession"]

_SR = 16_000
_MIN_NEW_SECONDS = 0.7          # don't re-run until this much new audio arrived
_KEEP_PROVISIONAL_SECONDS = 2.0  # never commit the last 2 s — it still changes
_MAX_TAIL_SECONDS = 28.0        # cap the tail we feed the model


def _pick_device() -> tuple[str, str]:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


class StreamingWhisper:
    def __init__(self, config: Config):
        self._model_name = config.voice.whisper_stream_model
        self._model = None
        self._lock = threading.Lock()   # one GPU transcription at a time

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise TranscribeError("faster-whisper not installed.") from e
            device, compute = _pick_device()
            self._model = WhisperModel(self._model_name, device=device, compute_type=compute)
        return self._model

    def session(self) -> "StreamSession":
        return StreamSession(self)

    # internal — run the model on a float32 array, return [(start, end, text)]
    def _run(self, audio) -> list[tuple[float, float, str]]:
        model = self._load()
        with self._lock:
            segments, _info = model.transcribe(
                audio, language="en", beam_size=1,
                condition_on_previous_text=False, vad_filter=False,
            )
            return [(s.start or 0.0, s.end or 0.0, s.text) for s in segments]


class StreamSession:
    def __init__(self, engine: StreamingWhisper):
        self._engine = engine
        self._buf = bytearray()            # raw PCM16 little-endian
        self._committed_text = ""
        self._committed_samples = 0        # samples consumed into _committed_text
        self._last_run_samples = 0

    # --- called from the WS handler ---------------------------------------
    def feed(self, pcm16: bytes) -> None:
        self._buf.extend(pcm16)

    @property
    def _total_samples(self) -> int:
        return len(self._buf) // 2

    def _tail_array(self):
        import numpy as np

        start = self._committed_samples
        cap = int(_MAX_TAIL_SECONDS * _SR)
        if self._total_samples - start > cap:
            start = self._total_samples - cap
        raw = bytes(self._buf[start * 2:])
        return np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0, start

    def poll(self) -> str | None:
        """Best full-text estimate, or None if not enough new audio yet."""
        if self._total_samples - self._last_run_samples < _MIN_NEW_SECONDS * _SR:
            return None
        self._last_run_samples = self._total_samples

        arr, tail_start = self._tail_array()
        if arr.size < _SR * 0.3:
            return None
        try:
            segs = self._engine._run(arr)
        except Exception as e:  # noqa: BLE001
            raise TranscribeError(str(e)) from e

        tail_dur = arr.size / _SR
        cutoff = tail_dur - _KEEP_PROVISIONAL_SECONDS
        newly_committed = []
        provisional = []
        for start, end, text in segs:
            (newly_committed if end <= cutoff else provisional).append((end, text))

        if newly_committed:
            self._committed_text = (
                self._committed_text + " " + " ".join(t.strip() for _, t in newly_committed)
            ).strip()
            last_end = newly_committed[-1][0]
            self._committed_samples = tail_start + int(last_end * _SR)

        interim = " ".join(t.strip() for _, t in provisional)
        return (self._committed_text + " " + interim).strip()

    def finish(self) -> str:
        """One last full pass over the un-committed tail; returns the whole text."""
        arr, _ = self._tail_array()
        if arr.size >= _SR * 0.2:
            try:
                segs = self._engine._run(arr)
                tail_text = " ".join(t.strip() for _, _, t in segs)
                return (self._committed_text + " " + tail_text).strip()
            except Exception:  # noqa: BLE001
                pass
        return self._committed_text.strip()
