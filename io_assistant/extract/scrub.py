"""Deterministic post-processing of an ExtractionResult.

Small local models (and Haiku) sometimes list a bare occupational/service role
noun as a *person* ("call the dentist" -> people: ["dentist"]). A role is not an
identified person — creating a `Person` row named "dentist" is junk. Drop such
names from the people lists (top-level and per-record); the record title still
carries the phrase, so nothing meaningful is lost.
"""

from __future__ import annotations

from io_assistant.models_domain import ExtractionResult

__all__ = ["scrub_roles"]

_ROLE_NOUNS = {
    "dentist", "doctor", "gp", "physician", "surgeon", "nurse", "therapist",
    "lawyer", "attorney", "solicitor", "accountant", "advisor", "agent",
    "plumber", "electrician", "mechanic", "handyman", "contractor", "builder",
    "barber", "hairdresser", "stylist", "cleaner", "gardener",
    "landlord", "tenant", "realtor",
    "boss", "manager", "supervisor", "colleague", "coworker", "assistant",
    "teacher", "professor", "tutor", "instructor", "coach", "trainer",
    "banker", "cashier", "clerk", "receptionist", "secretary",
    "waiter", "waitress", "server", "bartender", "barista", "chef",
    "driver", "cabbie", "courier",
    "babysitter", "nanny", "sitter", "vet", "veterinarian", "pharmacist",
}


def _is_role(name: str) -> bool:
    n = name.strip().lower()
    for prefix in ("the ", "a ", "an ", "my ", "our ", "his ", "her ", "their "):
        if n.startswith(prefix):
            n = n[len(prefix):]
    return n in _ROLE_NOUNS


def scrub_roles(result: ExtractionResult) -> ExtractionResult:
    dropped = {p.name.lower() for p in result.people if _is_role(p.name)}
    dropped |= {
        name.lower()
        for rec in result.records
        for name in rec.people
        if _is_role(name)
    }
    if not dropped:
        return result

    result.people = [p for p in result.people if p.name.lower() not in dropped]
    for rec in result.records:
        rec.people = [n for n in rec.people if n.lower() not in dropped]
        if rec.assigned_by and rec.assigned_by.lower() in dropped:
            rec.assigned_by = None
    return result
