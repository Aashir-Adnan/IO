"""Tier B pure helpers — catalogue matching + regex value extraction."""
from __future__ import annotations

import pytest

from io_assistant.web.trackers import (
    extract_reading, match_catalogue, value_from_text,
)


@pytest.mark.parametrize("text,label", [
    ("what's the usd to pkr rate", "USD to PKR"),
    ("keep an eye on the dollar to rupee", "USD to PKR"),
    ("track the bitcoin price", "Bitcoin price (USD)"),
    ("what's the gold price today", "Gold price (USD/oz)"),
])
def test_match_catalogue(text, label):
    spec = match_catalogue(text)
    assert spec is not None and spec.label == label


def test_match_catalogue_miss():
    assert match_catalogue("what's the news on korea") is None


@pytest.mark.parametrize("text,expected", [
    ("1 USD = 278.51 PKR", "278.51"),
    ("Bitcoin $63,240.10", "63240.10"),
    ("289", "289"),
    ("no numbers here", None),
])
def test_value_from_text(text, expected):
    assert value_from_text(text) == expected


def test_extract_reading_instant():
    assert extract_reading({"type": "instant"},
                           instant_text="1 USD = 278.51 PKR") == ("278.51", "")


def test_extract_reading_regex():
    got = extract_reading(
        {"type": "regex", "pattern": r"Rs\.?\s*([\d,.]+)", "unit": "PKR/L"},
        page_text="Petrol is now Rs. 289.50 per litre nationwide.",
    )
    assert got == ("289.50", "PKR/L")


def test_extract_reading_regex_no_match():
    assert extract_reading({"type": "regex", "pattern": r"Rs ([\d]+)"},
                           page_text="nothing") is None


def test_extract_reading_unknown_type():
    assert extract_reading({"type": "xpath"}, page_text="x") is None
