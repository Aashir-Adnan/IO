# Phone App Dart Ports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** The deterministic Python modules the chat loop depends on (date grounding, entity resolution, persistence, query) exist as tested Dart equivalents, so later tasks (chat screen, sync) have something real to call.

**Architecture:** Each module is a line-by-line behavioral port, not a reinterpretation: same function names (Dart-cased), same branches, same edge cases — verified by translating the existing Python pytest cases into Dart tests one-for-one. Where Python leans on `dateutil`'s fuzzy parser (no Dart equivalent of that scope exists), the port covers exactly the phrase shapes IO's own test suite exercises, not arbitrary natural language — documented inline as a `// ponytail:`-style scope note, not silently narrowed.

**Tech Stack:** Dart, `flutter_test`. No new pub packages needed for this plan (pure Dart, stdlib `DateTime` + regex).

**Spec:** `docs/superpowers/specs/2026-09-23-phone-app-design.md` §3

## Global Constraints

- No embeddings, no vector branch anywhere (already decided — lexical fallback only).
- `flutter analyze` clean and `flutter test` green before each commit.
- Every Dart test in this plan has a named Python counterpart it mirrors; where behavior is intentionally narrower (the absolute-date fallback), say so in a comment, not silently.

---

### Task 1: date grounding (`dates.py` → `lib/core/dates.dart`)

**Produces:** `DateResult` (`value: DateTime?`, `ok: bool`); `ground(String? phrase, DateTime now) -> DateResult`; `toRrule(String? phrase) -> String?`; `startOfDay(DateTime d) -> DateTime`; `isSomedayPhrase(String? text) -> bool`.

Mirrors `tests/test_dates.py` (46 cases) into `phone/test/core/dates_test.dart`, same phrases, same `NOW` fixture (`2026-09-07T15:00:00Z`, a Monday). The absolute-date fallback (`_parseAbsolute` equivalent) covers: ISO `YYYY-MM-DD`; `"the Nth of <month>"` / `"<month> Nth"` with ordinal suffixes and an optional junk prefix (matches the real "tomorrow, the 10th of september" case); year defaults to `now.year`, rolling to next year when the result lands more than a day in the past with no explicit 4-digit year; rejects phrases with no digit/month-name token. This is the documented narrower scope vs. `dateutil.parser.parse(fuzzy=True)`.

### Task 2: entity resolver, lexical-only (`resolver.py` → `lib/core/resolver.dart`)

**Consumes:** a `RowStore` interface over the local SQLite (candidate rows by name/alias, exact + `pg_trgm`-equivalent similarity — Dart has no trigram index, so this task also adds a pure-Dart trigram similarity function scored the same way, used only for ranking candidates already narrowed by a `LIKE`-style SQL prefilter, never a full-table Dart-side scan).

**Produces:** `ResolveOutcome` (`entityId`, `isNew`, `ambiguous`, `candidateId`, `candidateName`); `EntityResolver.resolve(type, name, aliases) -> ResolveOutcome`; `.lookup(type, name) -> int?`; `.create(type, name, aliases) -> int`. No vector branch at all (not "falls back to lexical" — *is* lexical, per the spec's decision).

Mirrors the exact-match and fuzzy-match branches of `resolve/resolver.py`; the vector branch (§3 "3. vector") is intentionally absent. Fuzzy scoring: a Dart token-set-ratio equivalent (word-set overlap ratio), tested against the same threshold behavior as `ResolverConfig.fuzzy_threshold`.

### Task 3: persistence pipeline (`persist/writer.py` → `lib/core/persist.dart`)

**Consumes:** Task 1 (`ground`, `startOfDay`, `isSomedayPhrase`), Task 2 (`EntityResolver`), the local SQLite schema (§2 of the design spec).

**Produces:** `persistStore(db, resolver, {utteranceText, source, capturedAt, extraction, now}) -> PersistResult` — creates/resolves entities, writes the record + link rows, applies default-today/roll-forward for a bare task/chore exactly as `writer.py` + the roll-forward rule from `tasks-and-collections.md` do.

### Task 4: query pipeline (`query/compile.py` + `retrieve.py` + `respond.py` → `lib/core/query.dart`)

**Produces:** `compileStructured(subQuery, entityIds, now) -> SqlQuery`-equivalent (a SQLite query builder, no semantic branch), `retrieve(db, subQuery, entityIds, now) -> List<RetrievedRow>`, `rowsToJson(rows, now) -> List<Map>` + `dueLabel`/`overdue` exactly as `respond.py`, `closeRecord` matching from `tasks/complete.py`.

---

## Self-review

Spec coverage: §3's five deterministic ports, minus the sync engine (its own plan, since it also needs the codec + transport, not just logic — see the memory-sync plan for the shape it should mirror). Scope note on the absolute-date parser is explicit, not a silent gap. Type/interface names carry across tasks unchanged (`DateResult`, `ResolveOutcome`, `EntityResolver`, `PersistResult`, `RetrievedRow`).
