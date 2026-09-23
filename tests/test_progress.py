"""Turn-progress breadcrumbs: the contextvar channel and the orchestrator's
emit points."""
from __future__ import annotations

from io_assistant.progress import emit, progress_to


def test_emit_is_a_noop_without_a_listener():
    emit("nobody is listening")  # must not raise


def test_progress_to_binds_and_unbinds():
    seen = []
    with progress_to(lambda s, d: seen.append((s, d))):
        emit("one", "a")
        emit("two")
    emit("after")  # listener unbound
    assert seen == [("one", "a"), ("two", "")]


def test_broken_listener_never_propagates():
    def boom(s, d):
        raise RuntimeError("listener bug")

    with progress_to(boom):
        emit("still fine")  # swallowed


def test_orchestrator_emits_stages(config, fake_backend, db, monkeypatch):
    import io_assistant.orchestrator as orch
    from io_assistant.models_domain import ExtractedRecord, ExtractionResult

    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())
    fake_backend.set_intent("store")
    fake_backend.set_extraction(ExtractionResult(
        records=[ExtractedRecord(kind="note", title="n", confidence=0.9)]))

    seen = []
    o = orch.Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    o.handle("note: n", on_progress=lambda s, d: seen.append(s))

    stages = " | ".join(seen)
    assert "Understanding what you said" in stages
    assert "Planning your request" in stages
    assert "Saving to memory" in stages
