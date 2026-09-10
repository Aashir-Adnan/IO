def test_records_has_completed_at(engine):
    from sqlalchemy import inspect
    cols = {c["name"] for c in inspect(engine).get_columns("records")}
    assert "completed_at" in cols
