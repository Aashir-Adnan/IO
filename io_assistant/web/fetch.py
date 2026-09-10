"""Fetch a result page and pull out its main text — stdlib `html.parser` only,
no lxml / readability / bs4. Good enough to feed a synthesis prompt: drop
script/style/nav/header/footer/aside/form, keep the longest text runs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

import httpx

__all__ = ["PageText", "fetch_and_extract", "extract_text", "WebFetchError"]

_TIMEOUT = httpx.Timeout(8.0, connect=3.0)
_SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside",
         "form", "svg", "button", "iframe", "template"}
_BLOCK = {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4",
          "h5", "h6", "br", "tr", "blockquote"}


class WebFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class PageText:
    url: str
    title: str
    text: str


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self.title = ""
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
        else:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in raw.split("\n")]
        # keep lines with real prose; a menu item is a word or two
        kept = [ln for ln in lines if len(ln) >= 40 or ln.endswith((".", "!", "?", ":"))]
        body = "\n".join(kept) if kept else "\n".join(ln for ln in lines if ln)
        return re.sub(r"\n{2,}", "\n\n", body).strip()


def extract_text(html: str) -> tuple[str, str]:
    """(title, text) from an HTML string. Pure — used directly in tests."""
    r = _Reader()
    try:
        r.feed(html)
    except Exception:  # malformed markup — take whatever parsed
        pass
    return re.sub(r"\s+", " ", r.title).strip(), r.text()


def fetch_and_extract(url: str, *, max_bytes: int = 400_000,
                      max_chars: int = 4_000) -> PageText:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; IO/1.0; local assistant)"}
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers=headers) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                ctype = resp.headers.get("content-type", "")
                if "html" not in ctype and "text" not in ctype and ctype:
                    raise WebFetchError(f"not text: {ctype}")
                buf = bytearray()
                for chunk in resp.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) >= max_bytes:
                        break
    except httpx.HTTPError as e:
        raise WebFetchError(f"fetch failed: {e}") from e

    html = buf.decode("utf-8", errors="replace")
    title, text = extract_text(html)
    return PageText(url=url, title=title, text=text[:max_chars])
