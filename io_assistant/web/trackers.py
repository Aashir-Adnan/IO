"""Tier B — a labelled web source polled on an interval so that
"petrol today vs yesterday" is a query over IO's own `reading` records.

A `Tracker` row holds a label, a normalised matcher key, a source, and an
`extractor` spec (JSONB):

  {"type": "instant", "query": "usd to pkr"}
      re-run the query against SearXNG and read the number out of its instant
      answer (currency / wikidata / calculator engines). Robust, no scraping.

  {"type": "regex", "pattern": "Rs\\.?\\s*([\\d,.]+)", "unit": "PKR/L"}
      fetch `source_url`, run the pattern over the extracted page text, take
      group 1 as the value.

No model is ever called on this path — extraction is a regex.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = [
    "TrackerSpec", "CATALOGUE", "match_catalogue", "normalize_label",
    "value_from_text", "extract_reading",
]

_WS = re.compile(r"\s+")
# a bare number, optionally with thousands separators / decimals / a leading -
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def normalize_label(s: str) -> str:
    return _WS.sub(" ", (s or "").strip().lower()).rstrip("?.! ")


@dataclass(frozen=True)
class TrackerSpec:
    label: str
    matcher: str                       # normalised key phrases, "|"-separated
    extractor: dict
    source_url: str = ""
    domain: str = "finance"
    interval_min: int = 720

    @property
    def keys(self) -> list[str]:
        return [k for k in self.matcher.split("|") if k]


CATALOGUE: dict[str, TrackerSpec] = {
    "usd-pkr": TrackerSpec(
        label="USD to PKR",
        matcher="usd to pkr|dollar to rupee|dollar rate|usd pkr|usd/pkr",
        extractor={"type": "instant", "query": "usd to pkr"},
        domain="finance", interval_min=360,
    ),
    "gbp-pkr": TrackerSpec(
        label="GBP to PKR",
        matcher="gbp to pkr|pound to rupee|pound rate",
        extractor={"type": "instant", "query": "gbp to pkr"},
        domain="finance", interval_min=360,
    ),
    "bitcoin": TrackerSpec(
        label="Bitcoin price (USD)",
        matcher="bitcoin price|btc price|price of bitcoin|btc to usd",
        extractor={"type": "instant", "query": "bitcoin price usd"},
        domain="finance", interval_min=120,
    ),
    "gold-usd": TrackerSpec(
        label="Gold price (USD/oz)",
        matcher="gold price|price of gold|gold rate",
        extractor={"type": "instant", "query": "gold price per ounce usd"},
        domain="finance", interval_min=360,
    ),
}


def match_catalogue(text: str) -> TrackerSpec | None:
    n = normalize_label(text)
    if not n:
        return None
    for spec in CATALOGUE.values():
        if any(k in n for k in spec.keys):
            return spec
    return None


def value_from_text(text: str) -> str | None:
    """First number in the text, separators stripped. '1 USD = 278.51 PKR' -> '278.51'
    (we take the last number when there is an '=' so we get the RHS)."""
    if not text:
        return None
    candidates = _NUMBER.findall(text)
    if not candidates:
        return None
    pick = candidates[-1] if "=" in text else candidates[0]
    return pick.replace(",", "")


def extract_reading(extractor: dict, *, instant_text: str = "",
                    page_text: str = "") -> tuple[str, str] | None:
    """Return (value, unit) or None. Pure — the caller supplies the fetched
    material so this stays trivially testable."""
    etype = (extractor or {}).get("type")
    if etype == "instant":
        v = value_from_text(instant_text)
        if v is None:
            return None
        return v, str(extractor.get("unit") or "")
    if etype == "regex":
        pat = extractor.get("pattern")
        if not pat:
            return None
        try:
            mo = re.search(pat, page_text)
        except re.error:
            return None
        if not mo:
            return None
        raw = (mo.group(1) if mo.groups() else mo.group(0)).replace(",", "")
        return raw, str(extractor.get("unit") or "")
    return None
