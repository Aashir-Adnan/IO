from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from io_assistant.backend.embed import Embedder
from io_assistant.backend.factory import build_backend
from io_assistant.config import Config
from io_assistant.db import models as m
from io_assistant.extract.acknowledge import build_fact_list
from io_assistant.extract.extractor import Extractor
from io_assistant.models_domain import ExtractionResult, Intent
from io_assistant.orchestrator_cards import query_cards, store_cards
from io_assistant.persist.writer import PersistError, PersistResult, persist_store
from io_assistant.query.pipeline import QueryPipeline
from io_assistant.resolve.resolver import EntityResolver
from io_assistant.route.router import Router

__all__ = ["HandleResult", "Orchestrator", "PendingStore"]


@dataclass
class PendingStore:
    """A gated store held for replay, so confirming re-uses the *same*
    utterance and the *same* extraction instead of re-running the LLM."""

    utterance_id: int
    extraction: ExtractionResult
    text: str
    source: str
    captured_at: datetime


@dataclass
class HandleResult:
    intent: Intent
    stored: PersistResult | None
    message: str
    pending: PendingStore | None = None
    cards: list = field(default_factory=list)
    intent_kind: str = "unknown"   # answer | ack | gate | unknown | error
    shape: str = "text"


class Orchestrator:
    def __init__(self, config: Config, session_factory, backend=None):
        self._config = config
        self._session_factory = session_factory
        self._backend = backend if backend is not None else build_backend(config)
        self._embedder = Embedder(config)
        self._router = Router(self._backend)
        self._extractor = Extractor(self._backend)
        self._query = QueryPipeline(self._backend, self._embedder, config.resolver)

    def handle(
        self,
        text: str,
        *,
        source: str = "text",
        captured_at: datetime | None = None,
        confirmed: bool = False,
        pending: PendingStore | None = None,
        history: str | None = None,
    ) -> HandleResult:
        """Acquire one session for the whole call, commit it (the verbatim
        utterance and any records), and always close it. A swallowed
        ``PersistError`` still returns normally, so the flushed utterance row
        is committed even when the write pass failed. ``history`` is the
        formatted recent-conversation string the service supplies; the CLI
        passes ``None``."""
        session = self._session_factory()
        try:
            result = self._handle_in_session(
                session,
                text,
                source=source,
                captured_at=captured_at,
                confirmed=confirmed,
                pending=pending,
                history=history,
            )
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _handle_in_session(
        self,
        session,
        text: str,
        *,
        source: str,
        captured_at: datetime | None,
        confirmed: bool,
        pending: PendingStore | None,
        history: str | None = None,
    ) -> HandleResult:
        if pending is not None:
            # Replay of a gated store: no Route, no Extract, no new utterance.
            return self._store(
                session,
                text=pending.text,
                source=pending.source,
                captured_at=pending.captured_at,
                now=pending.captured_at,
                extraction=pending.extraction,
                confirmed=True,
                existing_utterance_id=pending.utterance_id,
                history=history,
            )

        if captured_at is None:
            captured_at = datetime.now(timezone.utc)
        now = captured_at

        intent = self._router.classify(text, context=history)

        if intent == "unknown":
            return HandleResult(
                "unknown", None,
                "I didn't catch that - please rephrase and try again.",
                intent_kind="unknown",
            )

        if intent == "query":
            session.add(
                m.Utterance(
                    text=text,
                    source=source,
                    captured_at=captured_at,
                    resolved_intent="query",
                )
            )
            session.flush()
            answer = self._query.answer(session, text, now, context=history)
            return HandleResult(
                "query", None, answer.text,
                cards=query_cards(session, answer),
                intent_kind="answer", shape=answer.shape,
            )

        # intent == "store"
        extraction = self._extractor.run(text, now)

        if extraction is None:
            utt = m.Utterance(
                text=text,
                source=source,
                captured_at=captured_at,
                resolved_intent="store",
                marker="extraction_failed",
            )
            session.add(utt)
            session.flush()
            return HandleResult(
                "store", None, "I couldn't make sense of that to store it.",
                intent_kind="error",
            )

        return self._store(
            session,
            text=text,
            source=source,
            captured_at=captured_at,
            now=now,
            extraction=extraction,
            confirmed=confirmed,
            history=history,
        )

    def _store(
        self,
        session,
        *,
        text: str,
        source: str,
        captured_at: datetime,
        now: datetime,
        extraction: ExtractionResult,
        confirmed: bool,
        existing_utterance_id: int | None = None,
        history: str | None = None,
    ) -> HandleResult:
        resolver = EntityResolver(session, self._embedder, self._config.resolver)
        try:
            result = persist_store(
                session,
                self._embedder,
                resolver,
                utterance_text=text,
                source=source,
                captured_at=captured_at,
                extraction=extraction,
                now=now,
                confidence_gate=self._config.resolver.confidence_gate_threshold,
                confirmed=confirmed,
                existing_utterance_id=existing_utterance_id,
            )
        except PersistError as e:
            # The write pass rolled back to its SAVEPOINT; the utterance row
            # flushed before it is still live in this session and the caller
            # commits after we return. Never re-raise — that would take the
            # verbatim utterance down with the failed write.
            return HandleResult(
                "store",
                None,
                "Something went wrong while storing that — I've kept a note "
                f"of what you said, but couldn't file it. ({e})",
                intent_kind="error",
            )

        if result.gated:
            suffix = (
                " Reply 'yes' to use it, or rephrase."
                if any(r.startswith("ambiguous ") for r in result.gate_reasons)
                else " Reply 'yes' to confirm."
            )
            joined = "; ".join(result.gate_reasons)
            if not joined.endswith(("?", ".", "!")):
                joined += "."
            message = "Before I store this: " + joined + suffix
            return HandleResult(
                "store",
                result,
                message,
                intent_kind="gate",
                pending=PendingStore(
                    utterance_id=result.utterance_id,
                    extraction=extraction,
                    text=text,
                    source=source,
                    captured_at=captured_at,
                ),
            )

        facts = build_fact_list(session, result, extraction, now)
        try:
            message = self._backend.acknowledge(facts, context=history)
        except Exception:
            message = "Stored: " + self._summarize(session, result)
        message = (message or "").strip() or "Stored: " + self._summarize(session, result)
        return HandleResult(
            "store", result, message,
            cards=store_cards(session, result), intent_kind="ack",
        )

    def _summarize(self, session, result: PersistResult) -> str:
        by_id = {
            r.id: r
            for r in session.query(m.Record)
            .filter(m.Record.id.in_(result.record_ids))
            .all()
        }
        clauses: list[str] = []
        for rid in result.record_ids:
            rec = by_id.get(rid)
            if rec is None:
                continue
            clause = f'{rec.kind} "{rec.title}"'

            names = [
                n
                for (n,) in session.query(m.Person.canonical_name)
                .join(m.RecordPerson, m.RecordPerson.person_id == m.Person.id)
                .filter(m.RecordPerson.record_id == rid)
                .all()
            ]
            if names:
                clause += f"; people: {', '.join(names)}"

            places = [
                n
                for (n,) in session.query(m.Place.name)
                .join(m.RecordPlace, m.RecordPlace.place_id == m.Place.id)
                .filter(m.RecordPlace.record_id == rid)
                .all()
            ]
            if len(places) == 1:
                clause += f"; place: {places[0]}"
            elif len(places) > 1:
                clause += f"; places: {', '.join(places)}"

            if rec.due_at is not None:
                clause += f"; due {rec.due_at.date()}"

            clauses.append(clause)

        return " | ".join(clauses)
