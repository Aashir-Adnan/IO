# Skill: add an entity type / life domain

## First ask: does this need a table at all?

Almost never. The `records` table is open-ended. A new category of thing that
happened / is to be done / is a note is just a **new `kind` slug** (and maybe a
new `domain` value) that the model coins at extraction time — lowercase
snake_case, stored as data. `gym_session`, `health_note`, `job_task`,
`expense`: **zero code, zero migration.** Just make sure the extraction
few-shots and the query planner few-shots have an example in that shape so the
model reaches for a consistent slug, and (if it is a new `domain`) add the value
to the known-set clamp in the extractor.

## The heavy path: a dedicated new table

Reserved for a category that clearly outgrows `records` — it has several
first-class structured fields of its own, its own identity/dedup rules, or it is
linked to from many places. Example candidates: none in Phase 1. When it is
genuinely warranted:

1. Add the ORM model in `io_assistant/db/models.py` plus its link table(s)
   (`<thing>_people` etc.), with an `embedding vector` column and HNSW index,
   b-tree on FKs and timestamps.
2. Write the Alembic migration (`uv run alembic revision --autogenerate`, then
   review it — no ad-hoc `ALTER`).
3. Extend `io_assistant/extract/schema.py` (Pydantic) and add few-shot examples
   to the extraction prompt.
4. Add a resolver branch in `resolve/` (exact → fuzzy → vector → new) if the
   entity needs identity resolution.
5. Add persist handling in `persist/` (insert, link rows, embedding).
6. Add fixtures to `tests/fixtures/utterances_store.json` and write tests
   (resolver unit matrix, extraction fixture, an e2e scenario). TDD — tests
   first.
