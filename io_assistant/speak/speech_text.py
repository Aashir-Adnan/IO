from __future__ import annotations

import re

from io_assistant.speak.text import flatten_markdown

__all__ = ["prep_for_speech", "split_sentences"]

_ABBR = {
    r"\bDr\.": "Doctor", r"\bMr\.": "Mister", r"\bMrs\.": "Missus",
    r"\bMs\.": "Miz", r"\bSt\.": "Saint", r"\bvs\.": "versus",
    r"\bapprox\.": "approximately", r"\betc\.": "and so on",
    r"\bMon\b": "Monday", r"\bTue\b": "Tuesday", r"\bTues\b": "Tuesday",
    r"\bWed\b": "Wednesday", r"\bThu\b": "Thursday", r"\bThur\b": "Thursday",
    r"\bThurs\b": "Thursday", r"\bFri\b": "Friday", r"\bSat\b": "Saturday",
    r"\bSun\b": "Sunday",
}

_NUM_WORDS = {
    0: "twelve", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven",
    12: "twelve",
}


def _time_to_words(m: "re.Match[str]") -> str:
    h = int(m.group(1))
    mm = int(m.group(2))
    part = "in the morning" if h < 12 else "in the evening"
    h12 = h % 12 or 12
    hw = _NUM_WORDS.get(h12, str(h12))
    if mm == 0:
        return f"{hw} o'clock {part}"
    if mm == 15:
        return f"quarter past {hw} {part}"
    if mm == 30:
        return f"half past {hw} {part}"
    if mm == 45:
        nxt = (h12 % 12) + 1
        return f"quarter to {_NUM_WORDS.get(nxt, str(nxt))} {part}"
    return f"{hw} {mm:02d} {part}"


def _money(m: "re.Match[str]") -> str:
    unit = {"£": "pounds", "$": "dollars", "€": "euros"}[m.group(1)]
    return f"{m.group(2)} {unit}"


def prep_for_speech(s: str) -> str:
    """Markdown/answer text -> prose tuned for Piper. Deterministic, pure."""
    s = flatten_markdown(s)
    for pat, rep in _ABBR.items():
        s = re.sub(pat, rep, s)
    s = re.sub(r"\bQ([1-4])\b", r"Q \1", s)
    s = re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", _time_to_words, s)
    s = re.sub(r"([£$€])\s?(\d[\d,]*)", _money, s)
    s = s.replace("—", ", ").replace(" - ", ", ")
    s = re.sub(r"\(([^)]+)\)", r", \1,", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def split_sentences(s: str) -> list[str]:
    """Split on sentence marks (kept); further split clauses over 180 chars."""
    rough = re.findall(r"[^.?!]+[.?!]?", s)
    out: list[str] = []
    for chunk in rough:
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk) <= 180:
            out.append(chunk)
            continue
        for piece in re.split(r"(?<=[;,])\s+", chunk):
            piece = piece.strip()
            if piece:
                out.append(piece)
    return out
