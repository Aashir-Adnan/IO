from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz
from sqlalchemy import func, or_, select

from io_assistant.backend.embed import embed_or_none
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

    def _candidate_rows(
        self, entity_type: EntityType, name: str, aliases: list[str]
    ) -> list[tuple]:
        """Narrow to a bounded candidate set in SQL: an exact/overlap match on
        name or aliases[], UNION a trigram-similarity match on the name column
        (backed by ix_*_name_trgm). Never a full-table scan."""
        model, name_col = self._model_col(entity_type)
        needles = [name, *aliases]
        lowered = [n.lower() for n in needles]

        alias_text = func.array_to_string(model.aliases, " ")
        exact = select(model.id, name_col, model.aliases).where(
            or_(
                func.lower(name_col).in_(lowered),
                model.aliases.op("&&")(needles),  # array overlap (exact case)
            )
        )
        # pg_trgm similarity() is case-insensitive; the name-column comparison
        # uses ix_*_name_trgm, the alias one is a cheap expression filter.
        trgm = (
            select(model.id, name_col, model.aliases)
            .where(
                or_(
                    func.similarity(name_col, name) > 0.3,
                    func.similarity(alias_text, name) > 0.3,
                )
            )
            .order_by(
                func.greatest(
                    func.similarity(name_col, name),
                    func.similarity(alias_text, name),
                ).desc()
            )
            .limit(50)
        )
        rows: dict[int, tuple] = {}
        for cid, cname, caliases in self.session.execute(exact).all():
            rows[cid] = (cid, cname, caliases)
        for cid, cname, caliases in self.session.execute(trgm).all():
            rows.setdefault(cid, (cid, cname, caliases))
        return list(rows.values())

    def resolve(
        self, entity_type: EntityType, name: str, aliases: list[str]
    ) -> ResolveOutcome:
        model, name_col = self._model_col(entity_type)
        lowered = name.lower()
        incoming = {a.lower() for a in aliases}

        rows = self._candidate_rows(entity_type, name, aliases)

        # 1. exact: incoming name/alias vs stored name/alias, case-insensitive
        for cid, cname, caliases in rows:
            stored = {cname.lower(), *[a.lower() for a in (caliases or [])]}
            if lowered in stored or cname.lower() in incoming or (stored & incoming):
                return ResolveOutcome(cid, False, False, None, None)

        # 2. fuzzy: best token_set_ratio over the name AND every stored alias
        best_id: int | None = None
        best_score = -1.0
        for cid, cname, caliases in rows:
            score = max(
                fuzz.token_set_ratio(name, c)
                for c in (cname, *(caliases or []))
            )
            if score > best_score:
                best_score = score
                best_id = cid
        if best_id is not None and best_score >= self.cfg.fuzzy_threshold:
            return ResolveOutcome(best_id, False, False, None, None)

        # 3. vector: cosine search, similarity = 1 - distance (skipped when no
        #    embedder is available — exact + fuzzy above are the lexical path)
        vec = embed_or_none(self.embedder, name)
        if vec is not None:
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

    def lookup(self, entity_type: EntityType, name: str) -> int | None:
        """Read-only resolve for queries: exact -> fuzzy -> vector, best id or
        None. No create, no gate — a near vector match still counts."""
        rows = self._candidate_rows(entity_type, name, [])
        lowered = name.lower()
        for cid, cname, caliases in rows:
            stored = {cname.lower(), *[a.lower() for a in (caliases or [])]}
            if lowered in stored:
                return cid
        best_id: int | None = None
        best_score = -1.0
        for cid, cname, caliases in rows:
            score = max(
                fuzz.token_set_ratio(name, c) for c in (cname, *(caliases or []))
            )
            if score > best_score:
                best_score, best_id = score, cid
        if best_id is not None and best_score >= self.cfg.fuzzy_threshold:
            return best_id

        vec = embed_or_none(self.embedder, name)
        if vec is None:
            return None
        model, _name_col = self._model_col(entity_type)
        dist = model.embedding.cosine_distance(vec).label("dist")
        row = self.session.execute(
            select(model.id, dist)
            .where(model.embedding.isnot(None))
            .order_by(dist.asc())
            .limit(1)
        ).first()
        if row is not None and (1.0 - float(row[1])) >= self.cfg.vector_similarity_threshold:
            return row[0]
        return None

    def create(self, entity_type: EntityType, name: str, aliases: list[str]) -> int:
        model, name_attr = _TABLES[entity_type]
        obj = model(**{name_attr: name, "aliases": list(aliases)})
        obj.embedding = embed_or_none(self.embedder, name)
        self.session.add(obj)
        self.session.flush()
        return obj.id
