from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from io_assistant.backend.embed import Embedder
from io_assistant.backend.factory import build_backend
from io_assistant.config import Config
from io_assistant.db import models as m
from io_assistant.extract.extractor import Extractor
from io_assistant.models_domain import Intent
from io_assistant.persist.writer import PersistResult, persist_store
from io_assistant.resolve.resolver import EntityResolver
from io_assistant.route.router import Router

__all__ = ["HandleResult", "Orchestrator"]


@dataclass
class HandleResult:
    intent: Intent
    stored: PersistResult | None
    message: str


class Orchestrator:
    def __init__(self, config: Config, session_factory, backend=None):
        self._config = config
        self._session_factory = session_factory
        self._backend = backend if backend is not None else build_backend(config)
        self._embedder = Embedder(config)
        self._router = Router(self._backend)
        self._extractor = Extractor(self._backend)

    def handle(
        self,
        text: str,
        *,
        source: str = "text",
        captured_at: datetime | None = None,
        confirmed: bool = False,
    ) -> HandleResult:
        if captured_at is None:
            captured_at = datetime.now(timezone.utc)
        now = captured_at

        intent = self._router.classify(text)

        if intent == "unknown":
            return HandleResult(
                "unknown", None, "I didn't catch that - please rephrase and try again."
            )

        if intent == "query":
            return HandleResult(
                "query",
                None,
                "Query answering isn't available yet (comes in Plan 2).",
            )

        # intent == "store"
        session = self._session_factory()
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
                "store", None, "I couldn't make sense of that to store it."
            )

        resolver = EntityResolver(session, self._embedder, self._config.resolver)
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
        )

        if result.gated:
            message = (
                "Before I store this: "
                + "; ".join(result.gate_reasons)
                + ". Reply 'yes' to confirm."
            )
            return HandleResult("store", result, message)

        message = "Stored: " + self._summarize(session, result)
        return HandleResult("store", result, message)

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
