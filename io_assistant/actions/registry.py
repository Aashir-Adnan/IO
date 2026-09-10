"""Capability registry — the named workflows the model may ask IO to run.

A `Step(kind="action", action="<slug>", args={...})` from the planner is
validated against this registry (slug known, args shape ok) and then dispatched
to a whitelisted handler. Unknown slugs are downgraded to a plain query by the
orchestrator.

See docs/superpowers/specs/2026-09-09-unified-decide-pipeline-design.md.
The combined `backend.decide` prompt gets `describe_capabilities()` as its
tool list; the split-mode planner never emits action steps yet.
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Capability", "REGISTRY", "describe_capabilities", "validate_action"]


@dataclass(frozen=True)
class Capability:
    slug: str
    summary: str                       # one line, shown to the model
    args: dict[str, str] = field(default_factory=dict)   # name -> "type: note"
    requires_files: bool = False       # only offered when config.files.enabled
    requires_web: bool = False         # only offered when config.web.enabled


REGISTRY: dict[str, Capability] = {
    "complete_record": Capability(
        slug="complete_record",
        summary=("Mark an existing OPEN task or list item as done / dropped — "
                 "'I finished the report', 'cross milk off the list', 'cancel "
                 "the dentist reminder'. NOT for a task the user still needs to "
                 "do (that is a store step)."),
        args={"what": "string — the task or item being completed, as the user "
                      "named it"},
    ),
    "open_folder": Capability(
        slug="open_folder",
        summary="Open a folder the user names and show its contents as a grid.",
        args={"name": "string — the folder name or phrase, e.g. 'Downloads'"},
        requires_files=True,
    ),
    "show_photos": Capability(
        slug="show_photos",
        summary=("Show photos/videos/scans — of the people, places, or "
                 "possessions named ('me and Nafay', 'my passport', 'the CNIC "
                 "card'). Use for 'pull up / find / show me my <document or "
                 "belonging>' too."),
        args={"of": "string[] — names to filter by: people, places, or things "
                    "like 'passport', 'CNIC', 'degree' (optional)"},
        requires_files=True,
    ),
    "search_files": Capability(
        slug="search_files",
        summary="Search the indexed files for an answer to a question.",
        args={"query": "string — what to look for"},
        requires_files=True,
    ),
    "track": Capability(
        slug="track",
        summary=("Start tracking a changing web figure over time (an exchange "
                 "rate, a commodity or crypto price) so later 'today vs "
                 "yesterday' questions are answered from memory. Use for "
                 "'keep an eye on / track / watch the <price/rate>'."),
        args={"label": "string — what to track, e.g. 'USD to PKR', 'bitcoin price'"},
        requires_web=True,
    ),
    "web": Capability(
        slug="web",
        summary=("Look something up on the web — current events, news, prices, "
                 "exchange rates, scores, weather, anything needing today's "
                 "real-world facts. NOT for the user's own life, notes, or files."),
        args={"query": "string — the question to research",
              "kind": "string — 'news' for headlines/events, 'fact' for a "
                      "specific figure or current value"},
        requires_web=True,
    ),
}


def describe_capabilities(*, files_enabled: bool, web_enabled: bool = False) -> str:
    """Compact list for the decide prompt — one line per capability."""
    lines = []
    for cap in REGISTRY.values():
        if cap.requires_files and not files_enabled:
            continue
        if cap.requires_web and not web_enabled:
            continue
        arg_bits = ", ".join(f"{k} ({v})" for k, v in cap.args.items()) or "no args"
        lines.append(f"- {cap.slug}: {cap.summary}  args: {arg_bits}")
    return "\n".join(lines)


def validate_action(slug: str, args: dict) -> tuple[str, dict] | None:
    """Return a cleaned (slug, args) if the action is known and its args are
    the right shape, else None (caller falls back to a query)."""
    cap = REGISTRY.get(slug)
    if cap is None or not isinstance(args, dict):
        return None
    clean = {k: v for k, v in args.items() if k in cap.args}
    return slug, clean
