from __future__ import annotations

import re

__all__ = ["chunk_text"]

_PARA = re.compile(r"\n\s*\n")


def _chars(tokens: int) -> int:
    return tokens * 4


def chunk_text(text: str, *, chunk_tokens: int, overlap: int, max_chunks: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    limit = _chars(chunk_tokens)
    ov = _chars(overlap)

    paras: list[str] = []
    for p in _PARA.split(text):
        p = p.strip()
        if not p:
            continue
        while len(p) > limit:
            paras.append(p[:limit])
            p = p[limit:]
        if p:
            paras.append(p)

    chunks: list[str] = []
    buf = ""
    for p in paras:
        if buf and len(buf) + 2 + len(p) > limit:
            chunks.append(buf)
            if len(chunks) >= max_chunks:
                return chunks
            buf = (buf[-ov:] + "\n\n" + p) if ov else p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if buf and len(chunks) < max_chunks:
        chunks.append(buf)
    return chunks[:max_chunks]
