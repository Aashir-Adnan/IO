from __future__ import annotations

from datetime import datetime

from io_assistant.backend.interface import Backend, BackendParseError
from io_assistant.query.plan import PlanError, QueryPlan, SubQuery, ground_plan

__all__ = ["Planner"]


class Planner:
    def __init__(self, backend: Backend):
        self._backend = backend

    def run(
        self, question: str, now: datetime, *, context: str | None = None
    ) -> QueryPlan:
        for attempt in (1, 2):
            try:
                raw = self._backend.plan(question, now, context=context)
                return ground_plan(raw, now)
            except (BackendParseError, PlanError):
                if attempt == 2:
                    break
        return QueryPlan(subqueries=[SubQuery(semantic_hint=question)])
