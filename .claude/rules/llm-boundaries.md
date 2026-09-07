# Rule: LLM boundaries

The model (local or cloud) is called ONLY for: route, extract, plan, phrase.
It must never: emit SQL, do date arithmetic, filter data, rank data, decide
entity identity. All of that is deterministic Python (resolve/, persist/,
query/, resolve/dates.py). This boundary is what makes the local/cloud backend
swap safe — a weaker model extracts less well but cannot corrupt the datastore.
