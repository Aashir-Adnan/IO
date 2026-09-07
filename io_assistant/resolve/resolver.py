from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz
from sqlalchemy import select

from io_assistant.config import ResolverConfig
from io_assistant.db import models as m

EntityType = Literal["person", "place", "item"]

_TABLES: dict[str, tuple[type, str]] = {
    "person": (m.Person, "canonical_name"),
    "place": (m.Place, "name"),
    "item": (m.Item, "name"),
}


@dataclass
class ResolveOutcome:
    entity_id: int | None
    is_new: bool
    ambiguous: bool
    candidate_id: int | None
    candidate_name: str | None


class EntityResolver:
    def __init__(self, session, embedder, cfg: ResolverConfig):
        self.session = session
        self.embedder = embedder
        self.cfg = cfg

    def _model_col(self, entity_type: EntityType):
        model, name_attr = _TABLES[entity_type]
        return model, getattr(model, name_attr)

    def resolve(
        self, entity_type: EntityType, name: str, aliases: list[str]
    ) -> ResolveOutcome:
        model, name_col = self._model_col(entity_type)
        lowered = name.lower()

        rows = self.session.execute(
            select(model.id, name_col, model.aliases)
        ).all()

        # 1. exact: case-insensitive on name column OR any element of aliases[]
        for cid, cname, caliases in rows:
            if cname.lower() == lowered or lowered in [
                a.lower() for a in (caliases or [])
            ]:
                return ResolveOutcome(cid, False, False, None, None)

        # 2. fuzzy: token_set_ratio >= threshold, pick highest
        best_id: int | None = None
        best_score = -1.0
        for cid, cname, _caliases in rows:
            score = fuzz.token_set_ratio(name, cname)
            if score > best_score:
                best_score = score
                best_id = cid
        if best_id is not None and best_score >= self.cfg.fuzzy_threshold:
            return ResolveOutcome(best_id, False, False, None, None)

        # 3. vector: cosine search, similarity = 1 - distance
        vec = self.embedder.embed_one(name)
        dist = model.embedding.cosine_distance(vec).label("dist")
        vstmt = (
            select(model.id, name_col, dist)
            .where(model.embedding.isnot(None))
            .order_by(dist.asc())
            .limit(1)
        )
        vrow = self.session.execute(vstmt).first()
        if vrow is not None:
            similarity = 1.0 - float(vrow[2])
            if similarity >= self.cfg.vector_similarity_threshold:
                return ResolveOutcome(None, False, True, vrow[0], vrow[1])

        # 4. none
        return ResolveOutcome(None, True, False, None, None)

    def create(self, entity_type: EntityType, name: str, aliases: list[str]) -> int:
        model, name_attr = _TABLES[entity_type]
        obj = model(**{name_attr: name, "aliases": list(aliases)})
        obj.embedding = self.embedder.embed_one(name)
        self.session.add(obj)
        self.session.flush()
        return obj.id
