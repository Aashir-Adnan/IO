from __future__ import annotations

from collections.abc import Iterable, Iterator

__all__ = ["segment_stream"]


def _rms_speech(frame: bytes, threshold: int = 500) -> bool:
    import array

    a = array.array("h")
    a.frombytes(frame)
    if not a:
        return False
    return (sum(x * x for x in a) / len(a)) ** 0.5 > threshold


def _make_detector(rate: int, aggressiveness: int):
    try:
        import webrtcvad

        vad = webrtcvad.Vad(aggressiveness)

        def is_speech(f: bytes) -> bool:
            try:
                return vad.is_speech(f, rate)
            except Exception:
                return _rms_speech(f)

        return is_speech
    except Exception:
        return _rms_speech


def segment_stream(
    frames: Iterable[bytes],
    *,
    rate: int,
    aggressiveness: int,
    frame_ms: int = 30,
    min_speech_ms: int = 300,
    max_silence_ms: int = 700,
    detector=None,
) -> Iterator[bytes]:
    """Feed 30 ms PCM16 mono frames; yield one concatenated blob per speech
    segment. Uses webrtcvad when available, an RMS threshold otherwise; pass
    `detector` (a `bytes -> bool` callable) to override (tests)."""
    is_speech = detector or _make_detector(rate, aggressiveness)

    buf: list[bytes] = []
    speech_ms = 0
    silence_ms = 0
    in_speech = False
    for frame in frames:
        if is_speech(frame):
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
