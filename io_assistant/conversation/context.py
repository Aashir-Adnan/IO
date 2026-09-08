from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Turn", "format_context"]


@dataclass
class Turn:
    role: str
    text: str


def format_context(turns: list[Turn], *, max_chars: int = 1400) -> str:
    lines = [
        f"{'you' if t.role == 'user' else 'io'}: {t.text.strip()}"
        for t in turns
    ]
    while lines and len("\n".join(lines)) > max_chars:
        lines.pop(0)
    return "\n".join(lines)
