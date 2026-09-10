import datetime as dt

from io_assistant.collections.registry import (
    upsert_collection, describe_collections, resolve_collection, checkable_kinds,
)
from io_assistant.models_domain import ExtractedCollection
from tests.conftest import requires_db

NOW = dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.timezone.utc)


def _prop(**kw):
    kw.setdefault("name", "watchlist")
    kw.setdefault("synonyms", ["movies to watch", "shows to watch"])
    kw.setdefault("checkable", True)
    return ExtractedCollection(item_noun="movie or show", **kw)


@requires_db
def test_first_item_creates_the_collection(db):
    c = upsert_collection(db, kind_slug="watchlist", proposal=_prop(),
                          example_record_id=None, now=NOW)
    assert c.kind_slug == "watchlist" and "movies to watch" in c.synonyms


@requires_db
def test_second_item_merges_synonyms_no_duplicate(db):
    upsert_collection(db, kind_slug="watchlist", proposal=_prop(), example_record_id=None, now=NOW)
    c = upsert_collection(db, kind_slug="watchlist",
                          proposal=_prop(synonyms=["films to see", "movies to watch"]),
                          example_record_id=None, now=NOW)
    assert sorted(c.synonyms) == sorted(set(c.synonyms))
    assert "films to see" in c.synonyms and c.name == "watchlist"
    assert db.query(type(c)).count() == 1


@requires_db
def test_resolve_by_slug_synonym_and_fuzzy(db):
    upsert_collection(db, kind_slug="watchlist", proposal=_prop(), example_record_id=None, now=NOW)
    assert resolve_collection(db, "watchlist").kind_slug == "watchlist"
    assert resolve_collection(db, "shows to watch").kind_slug == "watchlist"
    assert resolve_collection(db, "movies i wanna watch").kind_slug == "watchlist"
    assert resolve_collection(db, "grocery list") is None


@requires_db
def test_describe_and_checkable(db):
    upsert_collection(db, kind_slug="watchlist", proposal=_prop(), example_record_id=None, now=NOW)
    upsert_collection(db, kind_slug="restaurants",
                      proposal=ExtractedCollection(name="restaurants", item_noun="place",
                                                   synonyms=["places to eat"], checkable=False),
                      example_record_id=None, now=NOW)
    text = describe_collections(db)
    assert "watchlist" in text and "restaurants" in text
    assert checkable_kinds(db) == {"watchlist"}
