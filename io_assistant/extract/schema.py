from __future__ import annotations

import json

# A hand-written shape hint, NOT ExtractionResult.model_json_schema(). The verbose
# json-schema dump (with its $defs block) makes small local models like
# llama3.2:3b echo the schema back instead of extracting - they return
# {"$defs": {...}} and yield zero entities. This compact hint extracts correctly.
SCHEMA_JSON = '''Return a JSON object with EXACTLY these keys, each an array (use [] when empty):
people: [{"name": str, "aliases": [str], "confidence": 0..1}]
places: [{"name": str, "aliases": [str], "confidence": 0..1}]
items:  [{"name": str, "aliases": [str], "confidence": 0..1}]
occasions: [{"name": str, "date_phrase": str|null, "confidence": 0..1}]
records: [{"kind": str, "domain": str|null, "title": str, "body": str|null,
           "when_phrase": str|null, "due_phrase": str|null, "recurrence_phrase": str|null,
           "status": "open"|"done"|"dropped"|null, "assigned_by": str|null,
           "people": [str], "places": [str], "items": [str], "occasions": [str],
           "attributes": {}, "confidence": 0..1,
           "collection": {"name": str, "item_noun": str, "synonyms": [str], "checkable": bool} | null}]
kind: "event" (it happened), "task" (one-off to-do), "chore" (recurring to-do),
      or a short coined slug like "gym_session" / "job_meeting" / "expense".
domain: one of social, job, home, health, finance, learning, errand, other.
collection: set ONLY when this record is an item the user is adding to a
      personal list that is not event/task/chore (movies/shows to watch, books
      to read, gift ideas, restaurants to try). Use the SAME kind slug you would
      use to ask for the whole list. "checkable": true if items get watched /
      read / done. Fill it on the first item; you may omit it on later items.
Do NOT resolve dates - copy the raw phrase into *_phrase fields.'''

# Worked examples as INPUT -> OUTPUT pairs (one line of JSON per OUTPUT, no code
# fences). Small local models parrot fenced markdown examples verbatim in
# json-mode; the plain "INPUT:/OUTPUT:" shape keeps them anchored on the real
# utterance. Every OUTPUT line must be valid JSON that parses as ExtractionResult
# (enforced by tests/test_extract_schema.py).
_EXAMPLES = [
    (
        "I went out with Nafay to eat at Arcadian for his and Eelian's birthday",
        {"people": [{"name": "Nafay", "aliases": [], "confidence": 0.95},
                    {"name": "Eelian", "aliases": [], "confidence": 0.9}],
         "places": [{"name": "Arcadian", "aliases": [], "confidence": 0.9}],
         "items": [],
         "occasions": [{"name": "Nafay and Eelian's birthday", "date_phrase": None, "confidence": 0.8}],
         "records": [{"kind": "event", "domain": "social",
                      "title": "dinner with Nafay and Eelian", "when_phrase": "today",
                      "people": ["Nafay", "Eelian"], "places": ["Arcadian"], "items": [],
                      "occasions": ["Nafay and Eelian's birthday"],
                      "attributes": {"meal": "dinner"}, "confidence": 0.9}]},
    ),
    (
        "Mum asked me to pick up groceries tomorrow",
        {"people": [{"name": "Mum", "aliases": ["mom", "mother"], "confidence": 0.9}],
         "places": [], "items": [{"name": "groceries", "aliases": [], "confidence": 0.8}],
         "occasions": [],
         "records": [{"kind": "task", "domain": "home", "title": "pick up groceries",
                      "assigned_by": "Mum", "due_phrase": "tomorrow", "status": "open",
                      "items": ["groceries"], "attributes": {}, "confidence": 0.85}]},
    ),
    (
        "I take the trash out every Monday",
        {"people": [], "places": [], "items": [{"name": "trash", "aliases": [], "confidence": 0.7}],
         "occasions": [],
         "records": [{"kind": "chore", "domain": "home", "title": "take the trash out",
                      "recurrence_phrase": "every Monday", "status": "open",
                      "items": ["trash"], "attributes": {}, "confidence": 0.9}]},
    ),
    (
        "Did chest and triceps at the gym, bench went up to 80kg",
        {"people": [], "places": [], "items": [], "occasions": [],
         "records": [{"kind": "gym_session", "domain": "health", "title": "chest and triceps",
                      "body": "bench up to 80kg", "when_phrase": "today",
                      "attributes": {"lifts": {"bench_kg": 80}}, "confidence": 0.85}]},
    ),
    (
        "add Dune Part Two to my list of movies I want to watch",
        {"people": [], "places": [], "items": [], "occasions": [],
         "records": [{"kind": "watchlist", "domain": "other",
                      "title": "Dune Part Two", "status": "open",
                      "collection": {"name": "watchlist", "item_noun": "movie or show",
                                     "synonyms": ["movies to watch", "shows to watch", "watchlist"],
                                     "checkable": True},
                      "attributes": {"medium": "movie"}, "confidence": 0.9}]},
    ),
]

FEWSHOT = "\n".join(
    f"INPUT: {utt}\nOUTPUT: {json.dumps(out, separators=(',', ':'))}"
    for utt, out in _EXAMPLES
)
