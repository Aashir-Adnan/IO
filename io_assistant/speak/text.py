from __future__ import annotations

import re

__all__ = ["flatten_markdown"]

_FENCE = re.compile(r"```(\w*)\n.*?```", re.S)


def flatten_markdown(s: str) -> str:
    """Markdown / answer text -> plain prose suitable for TTS. Pure; no I/O."""

    def _fence(m: "re.Match[str]") -> str:
        return "a diagram" if m.group(1) == "mermaid" else "a code block"

    s = _FENCE.sub(_fence, s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"\*([^*]+)\*", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"^\s*#{1,6}\s*", "", s, flags=re.M)
    s = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", s, flags=re.M)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()
