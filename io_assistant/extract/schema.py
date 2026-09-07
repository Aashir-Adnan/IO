from __future__ import annotations

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
           "attributes": {}, "confidence": 0..1}]
kind: "event" (it happened), "task" (one-off to-do), "chore" (recurring to-do),
      or a short coined slug like "gym_session" / "job_meeting" / "expense".
domain: one of social, job, home, health, finance, learning, errand, other.
Do NOT resolve dates - copy the raw phrase into *_phrase fields.'''

FEWSHOT = '''
Every `record` needs `kind` and `title`. Use kind "event" for something that
happened, "task" for a one-off to-do, "chore" for a recurring one. For anything
that doesn't fit those, coin a short kind slug (e.g. "gym_session", "job_meeting",
"expense") and set `domain` to one of:
social, job, home, health, finance, learning, errand, other.

Utterance: "I went out with Nafay to eat at Arcadian for his and Eelian's birthday"
```json
{"people":[{"name":"Nafay","aliases":[],"confidence":0.95},
           {"name":"Eelian","aliases":[],"confidence":0.9}],
 "places":[{"name":"Arcadian","aliases":[],"confidence":0.9}],
 "items":[],
 "occasions":[{"name":"Nafay and Eelian's birthday","date_phrase":null,"confidence":0.8}],
 "records":[{"kind":"event","domain":"social","title":"went out to eat with Nafay and Eelian",
             "when_phrase":"today","people":["Nafay","Eelian"],"places":["Arcadian"],
             "occasions":["Nafay and Eelian's birthday"],
             "attributes":{"meal":"dinner"},"confidence":0.9}]}
```

Utterance: "Mum asked me to pick up groceries tomorrow"
```json
{"people":[{"name":"Mum","aliases":["mom","mother"],"confidence":0.9}],
 "places":[],"items":[{"name":"groceries","aliases":[],"confidence":0.8}],
 "occasions":[],
 "records":[{"kind":"task","domain":"home","title":"pick up groceries",
             "assigned_by":"Mum","due_phrase":"tomorrow","status":"open",
             "items":["groceries"],"attributes":{},"confidence":0.85}]}
```

Utterance: "I take the trash out every Monday"
```json
{"people":[],"places":[],"items":[{"name":"trash","aliases":[],"confidence":0.7}],
 "occasions":[],
 "records":[{"kind":"chore","domain":"home","title":"take the trash out",
             "recurrence_phrase":"every Monday","status":"open",
             "items":["trash"],"attributes":{},"confidence":0.9}]}
```

Utterance: "Did chest and triceps at the gym, bench went up to 80kg"
```json
{"people":[],"places":[],"items":[],"occasions":[],
 "records":[{"kind":"gym_session","domain":"health","title":"chest and triceps",
             "body":"bench up to 80kg","when_phrase":"today",
             "attributes":{"lifts":{"bench_kg":80}},"confidence":0.85}]}
```
'''
