def test_records_has_completed_at(engine):
    from sqlalchemy import inspect
    cols = {c["name"] for c in inspect(engine).get_columns("records")}
    assert "completed_at" in cols


def test_collections_table_exists(engine):
    from sqlalchemy import inspect
    t = inspect(engine)
    assert "collections" in t.get_table_names()
    cols = {c["name"] for c in t.get_columns("collections")}
    assert {"kind_slug", "synonyms", "field_hint", "item_noun"} <= cols
