from __future__ import annotations

import threading

__all__ = ["record_fixed", "record_until"]


def record_fixed(seconds: float, *, rate: int) -> bytes:
    import numpy as np
    import sounddevice as sd

    frames = sd.rec(int(seconds * rate), samplerate=rate, channels=1, dtype="int16")
    sd.wait()
    return np.asarray(frames, dtype="int16").tobytes()


def record_until(stop: threading.Event, *, rate: int) -> bytes:
    import numpy as np
    import sounddevice as sd

    chunks: list[bytes] = []
    with sd.InputStream(samplerate=rate, channels=1, dtype="int16") as stream:
        while not stop.is_set():
            data, _ = stream.read(int(rate * 0.1))
            chunks.append(np.asarray(data, dtype="int16").tobytes())
    return b"".join(chunks)
