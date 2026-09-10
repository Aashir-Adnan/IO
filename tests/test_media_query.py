import datetime as dt

from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.files.media_query import expand_self, media_nodes_for_terms
from io_assistant.files.tags import query_terms, salient_terms
from io_assistant.models_domain import (
    ExtractedPerson, ExtractedPlace, ExtractionResult,
)

NOW = dt.datetime(2026, 9, 9, tzinfo=dt.timezone.utc)


def test_salient_terms_me_and_nafay_in_hunza():
    ex = ExtractionResult(
        people=[ExtractedPerson(name="Nafay", confidence=0.9)],
        places=[ExtractedPlace(name="Hunza", confidence=0.9)],
    )
    specs = salient_terms(ex, "me and nafay in hunza", "Aashir")
    got = {(s.norm, s.kind) for s in specs}
    assert got == {("nafay", "person"), ("hunza", "place"),
                   ("me", "self"), ("aashir", "self")}


def test_query_terms_expands_me():
    assert query_terms("fetch all pictures of me and nafay", "Aashir") == \
        ["me", "aashir", "nafay"]


def test_expand_self():
    assert expand_self(["me", "nafay"], "Aashir") == ["me", "aashir", "nafay"]
    assert expand_self(["myself"], "") == ["me"]


def test_salient_terms_possession():
    from io_assistant.models_domain import ExtractedItem
    ex = ExtractionResult(items=[ExtractedItem(name="CNIC card", confidence=0.9)])
    specs = salient_terms(ex, "scan of my CNIC card", "Aashir")
    got = {(s.norm, s.kind) for s in specs}
    assert ("cnic card", "thing") in got
    assert ("me", "self") in got


@requires_db
def test_possession_lookup_matches_by_whole_word(db):
    from io_assistant.files.media_query import media_nodes_for_terms
    n = m.FileNode(path="/x/passport.jpg", path_key="/x/passport.jpg", kind="file",
                   media_kind="image", status="ok")
    db.add(n); db.flush()
    db.add(m.FileTag(file_id=n.id, term="CNIC card", norm="cnic card",
                     kind="thing", media_kind="image", source="caption"))
    db.flush()
    nodes, _ = media_nodes_for_terms(db, ["cnic"], owner_name="Aashir")
    assert [x.id for x in nodes] == [n.id]      # "cnic" is a whole word in "cnic card"


@requires_db
def test_media_nodes_ranked_by_tag_coverage(db):
    def node(name, tags):
        n = m.FileNode(path=f"/x/{name}", path_key=f"/x/{name}", kind="file",
                       media_kind="image", status="ok")
        db.add(n); db.flush()
        for term, kind in tags:
            db.add(m.FileTag(file_id=n.id, term=term, norm=term.lower(),
                             kind=kind, media_kind="image", source="caption"))
        db.flush()
        return n

    both = node("both.jpg", [("Nafay", "person"), ("Me", "self"), ("Aashir", "self")])
    one = node("one.jpg", [("Nafay", "person")])
    node("none.jpg", [("Priya", "person")])

    nodes, matched_all = media_nodes_for_terms(
        db, ["me", "nafay"], owner_name="Aashir")
    ids = [n.id for n in nodes]
    assert ids[0] == both.id           # covers both query terms -> ranks first
    assert one.id in ids
    assert matched_all is True
