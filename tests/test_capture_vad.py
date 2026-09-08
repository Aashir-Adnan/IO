from io_assistant.capture.vad import segment_stream

# Tests exercise the segmentation state machine with an explicit detector;
# webrtcvad's own speech/non-speech accuracy is not ours to test.
_SPEECH = b"S"
_SILENCE = b"."
_DET = lambda f: f == _SPEECH  # noqa: E731


def _frames(pattern, frame_ms=30):
    out = []
    for kind, ms in pattern:
        out += [_SPEECH if kind == "speech" else _SILENCE] * (ms // frame_ms)
    return out


def test_one_segment_between_silences():
    frames = _frames([("silence", 300), ("speech", 600), ("silence", 900),
                      ("speech", 450), ("silence", 300)])
    segs = list(segment_stream(frames, rate=16000, aggressiveness=0, detector=_DET))
    assert len(segs) == 2
    assert all(isinstance(s, bytes) and len(s) > 0 for s in segs)


def test_short_blip_is_dropped():
    frames = _frames([("silence", 300), ("speech", 90), ("silence", 900)])
    assert list(segment_stream(frames, rate=16000, aggressiveness=0, detector=_DET)) == []
