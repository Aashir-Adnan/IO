from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from io_assistant.config import ResolverConfig
from io_assistant.query.entities import resolve_query_entities
from io_assistant.query.planner import Planner
from io_assistant.query.rank import rank
from io_assistant.query.recur import expand_recurrences
from io_assistant.query.respond import Responder
from io_assistant.query.retrieve import retrieve_subquery
from io_assistant.resolve.resolver import EntityResolver

__all__ = ["QueryAnswer", "QueryPipeline"]

_TOP_N = 20


@dataclass
class QueryAnswer:
    text: str
    shape: str
    n_rows: int


class QueryPipeline:
    def __init__(self, backend, embedder, resolver_cfg: ResolverConfig):
        self._backend = backend
        self._embedder = embedder
        self._cfg = resolver_cfg

    def answer(self, session, question: str, now: datetime) -> QueryAnswer:
        embedder = self._embedder
        plan = Planner(self._backend).run(question, now)

        groups = []
        starts: list[datetime] = []
        ends: list[datetime] = []
        for sq in plan.subqueries:
            resolver = EntityResolver(session, embedder, self._cfg)
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

        text = Responder(self._backend).run(question, final, plan.answer_shape)
        return QueryAnswer(text, plan.answer_shape, len(final))
