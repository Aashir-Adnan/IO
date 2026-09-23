from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select

from io_assistant.backend.embed import embed_or_none
from io_assistant.config import FilesConfig, ResolverConfig
from io_assistant.db import models as m
from io_assistant.extract.extractor import Extractor
from io_assistant.files.paths import AccessGate
from io_assistant.files.tags import salient_terms, write_tags
from io_assistant.files.walk import classify_media
from io_assistant.models_domain import EntityRef, ExtractionResult
from io_assistant.resolve.resolver import EntityResolver

__all__ = ["PendingCaption", "CaptionResult", "apply_caption"]

_ETYPE_ATTR = (("person", "people"), ("place", "places"), ("item", "items"))
_ENTITY_NAME = {
    "person": m.Person.canonical_name, "place": m.Place.name,
    "item": m.Item.name, "occasion": m.Occasion.name,
}
_ENTITY_MODEL = {
    "person": m.Person, "place": m.Place, "item": m.Item, "occasion": m.Occasion,
}


@dataclass
class PendingCaption:
    file_id: int
    path: str
    text: str
    source: str
    extraction: ExtractionResult


@dataclass
class CaptionResult:
    gated: bool
    caption: str
    entities: list[EntityRef] = field(default_factory=list)
    gate_reasons: list[str] = field(default_factory=list)
    pending: PendingCaption | None = None


def _media_kind(path: Path) -> str | None:
    return classify_media(path.suffix, FilesConfig())


def apply_caption(session, path: Path, text: str, source: str, *,
                  gate: AccessGate, index, backend, embedder,
                  resolver_cfg: ResolverConfig, now,
                  confirmed: bool = False,
                  extraction: ExtractionResult | None = None,
                  owner_name: str = "") -> CaptionResult:
    gate.assert_allowed(path, registered_keys=index.authorized_keys(session))
    pk = gate.key(path)
    node = index.get(session, pk)
    if node is None:
        node = index.upsert_node(
            session, path=str(path), path_key=pk,
            parent_key=gate.key(path.parent), kind="file",
            media_kind=_media_kind(path), status="ok")

    session.add(m.FileCaption(file_id=node.id, text=text, source=source))
    node.caption = text

    if extraction is None:
        extraction = Extractor(backend).run(text, now) or ExtractionResult()

    resolver = EntityResolver(session, embedder, resolver_cfg)

    plan: list[tuple[str, str, list[str], object]] = []
    reasons: list[str] = []
    for etype, attr in _ETYPE_ATTR:
        for ent in getattr(extraction, attr):
            outcome = resolver.resolve(etype, ent.name, list(ent.aliases))
            plan.append((etype, ent.name, list(ent.aliases), outcome))
            if getattr(outcome, "ambiguous", False) and not confirmed:
                reasons.append(
                    f"is '{ent.name}' the {etype} '{outcome.candidate_name}'?")

    if reasons and not confirmed:
        return CaptionResult(
            gated=True, caption=text, gate_reasons=reasons,
            pending=PendingCaption(node.id, str(path), text, source, extraction))

    linked: list[tuple[str, int]] = []
    for etype, name, aliases, outcome in plan:
        if outcome.entity_id is not None:
            eid = outcome.entity_id
        elif getattr(outcome, "ambiguous", False):
            eid = outcome.candidate_id
        else:
            eid = resolver.create(etype, name, aliases)
        index.link_entity(session, node.id, etype, eid, source="caption")
        linked.append((etype, eid))

    for occ in extraction.occasions:
        existing = session.execute(
            select(m.Occasion).where(
                func.lower(m.Occasion.name) == occ.name.lower())
        ).scalars().first()
        if existing is not None:
            oid = existing.id
        else:
            obj = m.Occasion(name=occ.name)
            obj.embedding = embed_or_none(embedder, occ.name)
            session.add(obj)
            session.flush()
            oid = obj.id
        index.link_entity(session, node.id, "occasion", oid, source="caption")
        linked.append(("occasion", oid))

    node.embedding = embed_or_none(embedder, text)
    session.flush()

    # tokenised tags — the fast fuzzy layer. Attach entity ids where they
    # resolved so a tag can also be a link.
    by_norm: dict[str, tuple[str, int]] = {}
    for etype, eid in linked:
        nm = session.execute(
            select(_ENTITY_NAME[etype]).where(_ENTITY_MODEL[etype].id == eid)
        ).scalar_one_or_none()
        if nm:
            by_norm[nm.strip().lower()] = (etype, eid)
    specs = []
    for s in salient_terms(extraction, text, owner_name):
        hit = by_norm.get(s.norm)
        specs.append(s if hit is None else
                     type(s)(term=s.term, norm=s.norm, kind=s.kind,
                             entity_etype=hit[0], entity_id=hit[1]))
    write_tags(session, node.id, node.media_kind, specs, source="caption")

    refs: list[EntityRef] = []
    for etype, eid in linked:
        nm = session.execute(
            select(_ENTITY_NAME[etype]).where(_ENTITY_MODEL[etype].id == eid)
        ).scalar_one_or_none()
        if nm is not None:
            refs.append(EntityRef(etype=etype, id=eid, name=nm))
    return CaptionResult(gated=False, caption=text, entities=refs)
