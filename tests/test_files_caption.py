import datetime as dt
from pathlib import Path

from tests.conftest import requires_db, StubEmbedder
from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate
from io_assistant.files.store import FileIndex
from io_assistant.files.caption import apply_caption
from io_assistant.models_domain import (
    ExtractionResult, ExtractedPerson, ExtractedPlace, ExtractedRecord)
from io_assistant.db import models as m

NOW = dt.datetime(2026, 9, 8, tzinfo=dt.timezone.utc)


def _args(config, tmp_path, fake_backend):
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)])
    return dict(gate=AccessGate(cfg), index=FileIndex(lambda: None),
               backend=fake_backend, embedder=StubEmbedder(),
               resolver_cfg=config.resolver, now=NOW)


@requires_db
def test_caption_links_entities_no_record(db, config, fake_backend, tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    fake_backend.set_extraction(ExtractionResult(
        people=[ExtractedPerson(name="Nafay", confidence=0.95)],
        places=[ExtractedPlace(name="Attabad Lake", confidence=0.9)],
        records=[ExtractedRecord(kind="event", title="ignored", confidence=0.9)],
    ))
    res = apply_caption(db, tmp_path / "a.jpg", "me and Nafay at Attabad Lake",
                        "text", **_args(config, tmp_path, fake_backend))
    db.flush()
    assert res.gated is False
    assert {e.name for e in res.entities} == {"Nafay", "Attabad Lake"}
    node = db.query(m.FileNode).one()
    assert node.caption == "me and Nafay at Attabad Lake"
    assert node.embedding is not None
    assert db.query(m.FileCaption).count() == 1
    assert db.query(m.Record).count() == 0
    assert db.query(m.FileEntityLink).filter_by(source="caption").count() == 2


@requires_db
def test_caption_confirm_replays_without_reextraction(db, config, fake_backend, tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    extraction = ExtractionResult(people=[ExtractedPerson(name="Zayn", confidence=0.9)])
    a = _args(config, tmp_path, fake_backend)
    res = apply_caption(db, tmp_path / "a.jpg", "photo of Zayn", "text",
                        confirmed=True, extraction=extraction, **a)
    db.flush()
    assert res.gated is False and res.entities[0].name == "Zayn"
    assert "extract" not in fake_backend.calls  # extraction supplied
