from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from io_assistant.backend.embed import Embedder
from io_assistant.backend.factory import build_backend
from io_assistant.config import Config
from io_assistant.db import models as m
from io_assistant.decide.planner import DecidePlanner
from io_assistant.extract.acknowledge import build_fact_list
from io_assistant.models_domain import ExtractionResult, Intent, Plan, Step
from io_assistant.orchestrator_cards import query_cards, store_cards
from io_assistant.persist.writer import PersistError, PersistResult, persist_store
from io_assistant.progress import emit as _emit
from io_assistant.query.pipeline import QueryPipeline
from io_assistant.resolve.resolver import EntityResolver

__all__ = ["HandleResult", "Orchestrator", "PendingStore"]

# --- web-answers routing pre-check (regex, no model) -------------------------
# A strong web signal AND no first-person reference (which would make it a
# question about the user's own life/notes). The `web` decide-action catches
# anything these miss.
_WEB_NEWS = re.compile(
    r"\b(news|headlines?|breaking)\b|what'?s happening|what is happening"
    r"|latest (on|about|from|news)", re.I,
)
_WEB_FACT = re.compile(
    r"\bprice of\b|\bexchange rate\b|how much (is|are|does|do)\b"
    r"|\b(stock|share) price\b|\bweather (in|for|today|tomorrow|this)\b"
    r"|\bwho won\b|\b(usd|eur|gbp|pkr|inr|btc|eth)\b.{0,20}\bto\b"
    r"|\bcurrent(ly)?\b.{0,30}\b(price|rate|value|cost)\b"
    r"|\bhow'?s the (weather|market|traffic)\b", re.I,
)
_WEB_PERSONAL = re.compile(r"\b(my|mine|i|i'?m|i'?ve|we|we'?ve|our|us)\b", re.I)
_WEB_TRACK = re.compile(
    r"\b(track|keep an eye on|keep track of|watch|monitor|start following)\b", re.I,
)
_WEB_DELTA = re.compile(
    r"\b(vs|versus|compared? (to|with)|change[ds]?|difference|since)\b"
    r"|\byesterday\b|\blast week\b|\bthis week\b|\bmove[ds]?\b", re.I,
)


def _phrase_reading(d: dict, *, want_delta: bool) -> str:
    """Template a tracker reading. Pure — no model."""
    unit = (" " + d["unit"]) if d.get("unit") else ""
    when = "" if d.get("is_today") else " (as of my last check)"
    base = f"{d['label']} is {d['current_raw']}{unit}{when}."
    prior = d.get("prior")
    if not want_delta or not prior or prior.get("raw") is None:
        return base
    chg = d.get("change")
    if isinstance(chg, (int, float)) and chg != 0:
        direction = "up" if chg > 0 else "down"
        pct = d.get("pct")
        pct_bit = f" ({pct:+.2f}%)" if isinstance(pct, (int, float)) else ""
        return (f"{base} That's {direction} {abs(chg):g}{unit}{pct_bit} "
                f"from {prior['raw']}{unit} previously.")
    if isinstance(chg, (int, float)) and chg == 0:
        return f"{base} Unchanged from {prior['raw']}{unit} previously."
    return f"{base} Previously {prior['raw']}{unit}."


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
        self._planner = DecidePlanner(self._backend, config)
        self._query = QueryPipeline(self._backend, self._embedder, config.resolver)

        self._files = self._file_index = self._indexer = self._gate = None
        self._index_queue = None   # set by the service so _file_open defers indexing
        if config.files.enabled:
            from io_assistant.files.paths import AccessGate
            from io_assistant.files.store import FileIndex
            from io_assistant.files.index import FileIndexer
            from io_assistant.files.search import FileSearcher

            self._gate = AccessGate(config.files)
            self._file_index = FileIndex(self._session_factory)
            self._indexer = FileIndexer(self._embedder, self._backend,
                                        config.files, config.resolver)
            self._files = FileSearcher(self._embedder, self._backend,
                                       config.files, config.resolver)

    def handle(
        self,
        text: str,
        *,
        source: str = "text",
        captured_at: datetime | None = None,
        confirmed: bool = False,
        pending: PendingStore | None = None,
        history: str | None = None,
        on_progress=None,
    ) -> HandleResult:
        """Acquire one session for the whole call, commit it (the verbatim
        utterance and any records), and always close it. A swallowed
        ``PersistError`` still returns normally, so the flushed utterance row
        is committed even when the write pass failed. ``history`` is the
        formatted recent-conversation string the service supplies; the CLI
        passes ``None``. ``on_progress(stage, detail)`` receives turn
        breadcrumbs (see io_assistant.progress)."""
        from io_assistant.progress import progress_to

        with progress_to(on_progress):
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

        _emit("Understanding what you said")
        web_kind = self._web_precheck(text)
        if web_kind == "track" and not confirmed:
            return self._action_track(session, {"label": text}, text=text)
        if web_kind in ("news", "fact") and not confirmed:
            res = self._run_web(
                session, text, web_kind, now,
                source=source, captured_at=captured_at,
            )
            if res is not None:
                return res
            # web couldn't help — fall through to normal planning

        _emit("Planning your request")
        plan = self._planner.plan(text, now, context=history)
        kinds = ", ".join(dict.fromkeys(s.kind for s in plan.steps)) if plan.steps else "unknown"
        _emit("Plan ready", f"{len(plan.steps) or 1} step(s): {kinds}")
        results = [
            self._dispatch_step(
                session, step,
                text=text, source=source, captured_at=captured_at, now=now,
                confirmed=confirmed, history=history,
            )
            for step in (plan.steps or [Step(kind="unknown")])
        ]
        return self._merge_results(results)

    def _dispatch_step(
        self, session, step: Step, *, text, source, captured_at, now, confirmed, history,
    ) -> HandleResult:
        if step.kind == "unknown":
            return HandleResult(
                "unknown", None,
                "I didn't catch that - please rephrase and try again.",
                intent_kind="unknown",
            )

        if step.kind == "query":
            _emit("Searching your memory", step.question or text)
            session.add(m.Utterance(text=text, source=source, captured_at=captured_at,
                                    resolved_intent="query"))
            session.flush()
            answer = self._query.answer(session, step.question or text, now, context=history)
            _emit("Answer ready", f"{answer.n_rows} record(s) used")
            return HandleResult(
                "query", None, answer.text,
                cards=query_cards(session, answer),
                intent_kind="answer", shape=answer.shape,
            )

        if step.kind == "file":
            session.add(m.Utterance(text=text, source=source, captured_at=captured_at,
                                    resolved_intent="file"))
            session.flush()
            if not self._config.files.enabled:
                return HandleResult(
                    "file", None,
                    "I can't open files yet — enable [files] in config.toml first.",
                    intent_kind="unknown",
                )
            _emit("Reading your files", step.question or text)
            return self._file_turn(session, step.question or text, now, history)

        if step.kind == "action":
            _emit("Running", step.action or "")
            return self._run_action(session, step, text=text, source=source,
                                    captured_at=captured_at, now=now, history=history)

        # step.kind == "store"
        extraction = step.extraction
        if extraction is None:
            session.add(m.Utterance(text=text, source=source, captured_at=captured_at,
                                    resolved_intent="store", marker="extraction_failed"))
            session.flush()
            return HandleResult(
                "store", None, "I couldn't make sense of that to store it.",
                intent_kind="error",
            )
        n_rec = len(getattr(extraction, "records", []) or [])
        _emit("Saving to memory",
              f"{n_rec} record(s), "
              f"{len(getattr(extraction, 'people', []) or [])} people")
        return self._store(
            session, text=text, source=source, captured_at=captured_at, now=now,
            extraction=extraction, confirmed=confirmed, history=history,
        )

    @staticmethod
    def _merge_results(results: list[HandleResult]) -> HandleResult:
        """One step → return it. Several steps → one combined turn. A gate on
        any step pauses the whole turn (remaining steps are dropped for now)."""
        results = [r for r in results if r is not None]
        if not results:
            return HandleResult("unknown", None, "I didn't catch that.",
                                intent_kind="unknown")
        if len(results) == 1:
            return results[0]

        for r in results:
            if r.intent_kind == "gate":
                return r

        parts = [r.message.strip() for r in results if r.message and r.message.strip()]
        cards: list = []
        for r in results:
            cards.extend(r.cards or [])
        kinds = {r.intent_kind for r in results}
        intent_kind = "answer" if "answer" in kinds else ("ack" if "ack" in kinds else "unknown")
        stored = next((r.stored for r in results if r.stored is not None), None)
        primary = next((r.intent for r in results if r.intent == "query"), results[0].intent)
        shape = "markdown" if any(r.shape != "text" for r in results) or len(parts) > 1 else "text"
        return HandleResult(
            primary, stored, "\n\n".join(parts) or results[0].message,
            cards=cards, intent_kind=intent_kind, shape=shape,
        )

    def _run_action(self, session, step: Step, *, text, source, captured_at, now, history):
        """Dispatch a capability step. Phase 4 wires real handlers; for now an
        unknown or unhandled action degrades to a query so nothing breaks."""
        from io_assistant.actions.registry import validate_action

        checked = validate_action(step.action or "", step.args or {})
        handlers = self._action_handlers()
        if checked is None or checked[0] not in handlers:
            return self._dispatch_step(
                session, Step(kind="query", question=text),
                text=text, source=source, captured_at=captured_at, now=now,
                confirmed=False, history=history,
            )
        slug, args = checked
        return handlers[slug](
            session, args, text=text, source=source, captured_at=captured_at,
            now=now, history=history,
        )

    def _action_handlers(self):
        h = {
            "open_folder": self._action_open_folder,
            "show_photos": self._action_show_photos,
            "search_files": self._action_search_files,
        }
        if self._config.web.enabled:
            h["web"] = self._action_web
            h["track"] = self._action_track
        return h

    def _action_track(self, session, args, *, text, **_):
        from io_assistant.web.trackers import match_catalogue
        spec = match_catalogue(args.get("label") or text)
        if spec is None:
            return HandleResult(
                "query", None,
                "I don't have a way to track that yet — I can track exchange "
                "rates and gold/crypto prices.",
                intent_kind="unknown",
            )
        from io_assistant.web.poller import poll_tracker, register_tracker
        from io_assistant.web.search import WebSearcher

        tracker = register_tracker(session, spec)
        ok = poll_tracker(session, WebSearcher(self._config.web), tracker,
                          datetime.now(timezone.utc))
        session.flush()
        if ok and tracker.last_value:
            return HandleResult(
                "query", None,
                f"Tracking {spec.label} — it's {tracker.last_value}"
                f"{(' ' + tracker.last_unit) if tracker.last_unit else ''} right now. "
                f"I'll check every {spec.interval_min // 60 or 1}h so you can ask "
                f"how it's changed.",
                intent_kind="ack",
            )
        return HandleResult(
            "query", None,
            f"Tracking {spec.label} from now on. I couldn't read a value on the "
            f"first check — I'll keep trying.",
            intent_kind="ack",
        )

    def _action_web(self, session, args, *, text, source, captured_at, now, history, **_):
        raw_kind = str(args.get("kind") or "").lower()
        kind = "news" if raw_kind == "news" else "fact"
        res = self._run_web(session, args.get("query") or text, kind, now,
                            source=source, captured_at=captured_at)
        if res is not None:
            return res
        return HandleResult(
            "query", None,
            "I couldn't find anything current on that.",
            intent_kind="unknown",
        )

    def _action_open_folder(self, session, args, *, text, now, history, **_):
        from io_assistant.files.command import FileCommand
        return self._file_open(session, FileCommand(action="open", phrase=args.get("name") or text, path=None))

    def _action_search_files(self, session, args, *, text, now, history, **_):
        from io_assistant.files.cards import files_card
        answer = self._files.search(session, args.get("query") or text, now,
                                    gate=self._gate, context=history)
        return HandleResult("file", None, answer.text, cards=[files_card(answer)],
                            intent_kind="files", shape=answer.shape)

    def _action_show_photos(self, session, args, *, text, now, history, **_):
        from io_assistant.files.cards import gallery_card
        from io_assistant.files.gallery import gallery_from_nodes
        from io_assistant.files.media_query import media_nodes_for_terms, terms_from_question

        raw = args.get("of")
        if isinstance(raw, str):
            raw = [raw]
        terms = list(raw or []) or terms_from_question(text, self._config.owner_name)

        nodes, matched_all = media_nodes_for_terms(
            session, terms, owner_name=self._config.owner_name)
        if not nodes:
            who = ", ".join(t for t in terms if t) or "that"
            return HandleResult("file", None,
                                f"I don't have any photos or videos tagged with {who} yet.",
                                intent_kind="unknown")
        label = ("photos of " + ", ".join(terms)) if terms else "recent photos"
        card = gallery_from_nodes(session, nodes, label=label)
        pre = "" if matched_all or not terms else "Closest matches — "
        return HandleResult(
            "file", None,
            f"{pre}{card.count} item{'' if card.count == 1 else 's'}"
            + (f" of {', '.join(terms)}" if terms else ""),
            cards=[gallery_card(card)], intent_kind="gallery", shape="text")

    # --- web-backed answers (Tiers A & C; see io_assistant/web/) -------------
    def _web_precheck(self, text: str) -> str | None:
        """'news' | 'fact' | None — a deterministic first pass so the common
        shapes never cost a planner call."""
        if not self._config.web.enabled or not text:
            return None
        t = text.strip()
        if _WEB_TRACK.search(t):
            from io_assistant.web.trackers import match_catalogue
            if match_catalogue(t) is not None:
                return "track"
        if _WEB_PERSONAL.search(t):
            return None
        if _WEB_NEWS.search(t):
            return "news"
        if _WEB_FACT.search(t):
            return "fact"
        return None

    @property
    def _web_answerer(self):
        wa = getattr(self, "_web_answerer_cached", None)
        if wa is None:
            from io_assistant.web.answer import WebAnswerer
            wa = WebAnswerer(self._config, self._backend)
            self._web_answerer_cached = wa
        return wa

    def _run_web(self, session, question: str, kind: str, now, *,
                 source: str, captured_at: datetime) -> HandleResult | None:
        """Run the web path. Returns None (not a HandleResult) when it can't
        help, so the caller falls back to normal planning. Order: Tier B
        (own `reading` records) → Tier A/C (`WebAnswerer`)."""
        from io_assistant.models_domain import WebCard, WebSource

        _emit("Looking it up on the web", f"{kind}: {question}")
        tb = self._tracker_answer(session, question, now)
        if tb is not None:
            _emit("Answered from a tracked figure")
            session.add(m.Utterance(text=question, source=source,
                                    captured_at=captured_at,
                                    resolved_intent="query", marker="web"))
            session.flush()
            return HandleResult(
                "query", None, tb, cards=[WebCard(tier="b", kind="fact")],
                intent_kind="answer", shape="text",
            )

        try:
            ans = self._web_answerer.answer(session, question, kind=kind, now=now)
        except Exception:  # noqa: BLE001 — never let a web hiccup break the turn
            return None
        if ans is None:
            return None

        session.add(m.Utterance(text=question, source=source, captured_at=captured_at,
                                resolved_intent="query", marker="web"))
        session.flush()
        card = WebCard(
            tier=ans.tier, kind=ans.kind, cached=ans.cached,
            sources=[WebSource(title=s.get("title") or s.get("url") or "source",
                               url=s.get("url") or "")
                     for s in ans.sources if s.get("url")],
        )
        return HandleResult(
            "query", None, ans.text, cards=[card],
            intent_kind="answer", shape="text",
        )

    def _tracker_answer(self, session, question: str, now: datetime) -> str | None:
        """Answer from `reading` records if a tracker covers this figure.
        Registers + polls the tracker once if it's known but not yet running,
        so the first 'what's X' still gets a live number."""
        from io_assistant.web.trackers import match_catalogue

        spec = match_catalogue(question)
        if spec is None:
            return None
        from io_assistant.web.poller import (
            delta_reading, latest_readings, poll_tracker, register_tracker,
        )

        readings = latest_readings(session, spec.label)
        if not readings:
            try:
                from io_assistant.web.search import WebSearcher
                tracker = register_tracker(session, spec)
                poll_tracker(session, WebSearcher(self._config.web), tracker, now)
                session.flush()
            except Exception:  # noqa: BLE001
                return None
            readings = latest_readings(session, spec.label)
        d = delta_reading(readings, now)
        if d is None or d.get("current_raw") is None:
            return None
        return _phrase_reading(d, want_delta=bool(_WEB_DELTA.search(question)))

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

    def _file_turn(self, session, text: str, now, history) -> HandleResult:
        from io_assistant.files.cards import files_card
        from io_assistant.files.command import classify_file_command

        cmd = classify_file_command(text)
        if cmd.action == "register":
            return self._file_register(session, cmd)
        if cmd.action == "open":
            return self._file_open(session, cmd)
        # media / possession lookup ("pictures of me and Nafay", "pull up my
        # passport", "where's my CNIC card") -> a gallery via file_tags
        if re.search(
            r"\b(photos?|pictures?|pics?|videos?|clips?|scans?)\b"
            r"|\b(pull up|show me|bring up|find|get me|where('?s| is| are)?)\b.{0,30}\bmy\b",
            text, re.I,
        ):
            res = self._action_show_photos(session, {"of": None}, text=text,
                                           now=now, history=history)
            if res.intent_kind == "gallery":
                return res
        answer = self._files.search(session, text, now, gate=self._gate,
                                    context=history)
        return HandleResult(
            "file", None, answer.text, cards=[files_card(answer)],
            intent_kind="files", shape=answer.shape,
        )

    def _file_open(self, session, cmd) -> HandleResult:
        from io_assistant.files.cards import gallery_card
        from io_assistant.files.command import resolve_folder
        from io_assistant.files.gallery import open_folder
        from io_assistant.files.paths import AccessDenied

        target = None
        if cmd.path:
            try:
                target = self._gate.resolve(cmd.path)
            except AccessDenied as e:
                return HandleResult("file", None,
                                    f"I can't open that: {e.reason}.",
                                    intent_kind="error")
        else:
            res = resolve_folder(cmd.phrase or "", session, self._gate,
                                 self._config.files)
            if res.kind == "one":
                target = res.path
            elif res.kind == "many":
                names = ", ".join(p.name for p in res.candidates)
                return HandleResult("file", None,
                                    f"I found a few — which one? {names}",
                                    intent_kind="unknown")
            else:
                return HandleResult("file", None,
                                    "I couldn't find a folder called that.",
                                    intent_kind="unknown")
        try:
            card = open_folder(session, target, gate=self._gate,
                               index=self._file_index, config=self._config.files,
                               index_queue=getattr(self, "_index_queue", None))
        except AccessDenied as e:
            return HandleResult("file", None, f"I can't open that: {e.reason}.",
                                intent_kind="error")
        return HandleResult(
            "file", None,
            f"Opening {target.name} — {card.count} item(s).",
            cards=[gallery_card(card)], intent_kind="gallery", shape="text")

    def _file_register(self, session, cmd) -> HandleResult:
        from io_assistant.files.command import resolve_register_target
        from io_assistant.files.paths import AccessDenied

        target = None
        if cmd.path:
            try:
                target = self._gate.resolve(cmd.path)
            except AccessDenied as e:
                return HandleResult("file", None,
                                    f"I can't read that: {e.reason}.",
                                    intent_kind="error")
        else:
            res = resolve_register_target(cmd.phrase or "", session, self._gate,
                                          self._config.files)
            if res.kind == "one":
                target = res.path
            elif res.kind == "many":
                names = ", ".join(p.name for p in res.candidates)
                return HandleResult("file", None,
                                    f"I found a few — which one? {names}",
                                    intent_kind="unknown")
            else:
                return HandleResult(
                    "file", None,
                    "I couldn't find that folder under your indexed locations.",
                    intent_kind="unknown")
        try:
            result = self._file_index.register(session, target, self._gate,
                                               self._config.files)
        except AccessDenied as e:
            return HandleResult("file", None, f"I can't read that: {e.reason}.",
                                intent_kind="error")
        for node in self._file_index.stale(session):
            self._indexer.index_path(session, Path(node.path), gate=self._gate)
        return HandleResult(
            "file", None,
            f"Indexed {target.name} — {result.discovered} file(s).",
            intent_kind="ack",
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
