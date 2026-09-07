from __future__ import annotations

from io_assistant.config import Config
from io_assistant.backend.interface import Backend
from io_assistant.backend.local import LocalBackend
from io_assistant.backend.anthropic_backend import AnthropicBackend
from io_assistant.backend.hybrid import HybridBackend


def build_backend(config: Config) -> Backend:
    p = config.backend.provider
    if p == "local":
        return LocalBackend(config)
    if p == "anthropic":
        return AnthropicBackend(config)
    if p == "hybrid":
        return HybridBackend(LocalBackend(config), AnthropicBackend(config))
    raise ValueError(f"unknown backend provider: {p}")
