# Rule: local-first

IO runs entirely on the user's machine by default. The ONLY permitted non-local
network traffic is to `api.anthropic.com`, and ONLY when `backend.provider` in
config.toml is "anthropic" or "hybrid". No telemetry, no analytics, no CDN
assets, no bundled cloud calls. Any other outbound connection to a non-local
host is a bug. The test suite enforces this (`tests/test_e2e_store.py` socket
guard).
