from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select

from io_assistant.config import ResolverConfig
from io_assistant.db import models as m
from io_assistant.query.entities import resolve_query_entities
from io_assistant.query.planner import Planner
from io_assistant.query.rank import rank
from io_assistant.query.recur import expand_recurrences
from io_assistant.query.respond import Responder
from io_assistant.query.retrieve import retrieve_subquery
from io_assistant.progress import emit as _emit
from io_assistant.resolve.resolver import EntityResolver

__all__ = ["QueryAnswer", "QueryPipeline", "RecordRef"]

_TOP_N = 20


@dataclass
class RecordRef:
    record_id: int
    kind: str
    domain: str | None
    title: str
    status: str | None
    when: datetime | None
    due: datetime | None


@dataclass
class QueryAnswer:
    text: str
    shape: str
    n_rows: int
    source_record_ids: list[int] = field(default_factory=list)
    list_records: list[RecordRef] = field(default_factory=list)


def _project(session, rows) -> list[RecordRef]:
    seen: dict[int, None] = {}
    for r in rows:
        if getattr(r, "target_type", "record") == "record":
            seen.setdefault(r.obj.id, None)
    ids = list(seen)
    if not ids:
        return []
    by_id = {
        rec.id: rec
        for rec in session.execute(
            select(m.Record).where(m.Record.id.in_(ids))
        ).scalars().all()
    }
    out: list[RecordRef] = []
    for rid in ids:
        rec = by_id.get(rid)
        if rec is None:
            continue
        out.append(RecordRef(
            record_id=rec.id, kind=rec.kind, domain=rec.domain, title=rec.title,
            status=rec.status, when=rec.occurred_at, due=rec.due_at,
        ))
    return out


class QueryPipeline:
    def __init__(self, backend, embedder, resolver_cfg: ResolverConfig):
        self._backend = backend
        self._embedder = embedder
        self._cfg = resolver_cfg

    def answer(
        self, session, question: str, now: datetime, *, context: str | None = None
    ) -> QueryAnswer:
        from io_assistant.collections.registry import routing_preamble

        embedder = self._embedder
        plan_ctx = routing_preamble(session) + (context or "") or None
        plan = Planner(self._backend).run(question, now, context=plan_ctx)
        _emit("Retrieval plan ready",
              f"{len(plan.subqueries)} subquery(ies), "
              f"target {plan.subqueries[0].target_type if plan.subqueries else '?'}")

        groups = []
        starts: list[datetime] = []
        ends: list[datetime] = []
        for sq in plan.subqueries:
            resolver = EntityResolver(session, embedder, self._cfg)
            _emit("Resolving people & places", ", ".join(sq.entities) or "—")
            ids = resolve_query_entities(resolver, session, sq.entities)
            groups.append(retrieve_subquery(session, embedder, sq, ids, now))
            if sq.time_window is not None:
                if sq.time_window.start is not None:
                    starts.append(sq.time_window.start)
                if sq.time_window.end is not None:
                    ends.append(sq.time_window.end)

        ranked = rank(groups, now, top_n=_TOP_N)

        lo = min(starts, default=None)
        hi = max(ends, default=None)
        expanded = expand_recurrences(ranked, lo, hi, now=now)
        expanded.sort(key=lambda r: r.score, reverse=True)
        final = expanded[:_TOP_N]

        _emit("Writing the answer", f"{len(final)} row(s) matched")
        text = Responder(self._backend).run(
            question, final, plan.answer_shape, now=now, context=context
        )
        record_refs = _project(session, final)
        return QueryAnswer(
            text=text,
            shape=plan.answer_shape,
            n_rows=len(final),
            source_record_ids=[r.record_id for r in record_refs],
            list_records=record_refs,
        )
