"""Opt-in web-backed answers. Off unless config.toml [web].enabled = true.

Three tiers, minimal AI (see docs/superpowers/specs/2026-09-09-web-answers-design.md):
  A  instant answers from SearXNG infoboxes/answers  — 0 fetches, 0 model calls
  B  trackable facts polled into `reading` records   — 0 model calls at query time
  C  news / open synthesis                           — exactly 1 cached model call

`rules/local-first.md` cases 3–5 sanction the SearXNG localhost port and the
result-page fetches, only while [web].enabled.
"""
