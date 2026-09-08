from __future__ import annotations

import importlib.util
import os
import shutil
from dataclasses import dataclass

from io_assistant.config import Config, whisper_model_for

__all__ = ["Check", "run_checks", "format_report"]


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def _check_postgres(config: Config) -> Check:
    from sqlalchemy import create_engine, text

    try:
        eng = create_engine(config.database_url)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return Check("PostgreSQL", True, config.database_url.split("@")[-1])
    except Exception as e:  # noqa: BLE001
        return Check("PostgreSQL", False, str(e)[:120])


def _check_pgvector(config: Config) -> Check:
    from sqlalchemy import create_engine, text

    try:
        eng = create_engine(config.database_url)
        with eng.connect() as conn:
            n = conn.execute(
                text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
            ).scalar()
        return Check("pgvector", bool(n), "installed" if n else "extension missing")
    except Exception as e:  # noqa: BLE001
        return Check("pgvector", False, str(e)[:120])


def _ollama_tags(config: Config) -> list[str]:
    import httpx

    url = config.backend.ollama_url.rstrip("/") + "/api/tags"
    data = httpx.get(url, timeout=3).json()
    return [m.get("name", "") for m in data.get("models", [])]


def _check_backend(config: Config) -> Check:
    provider = config.backend.provider
    if provider in ("anthropic", "hybrid"):
        has = bool(
            os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )
        return Check(
            "backend",
            has,
            f"{provider}: credential present" if has
            else f"{provider}: set ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN",
        )
    try:
        tags = _ollama_tags(config)
    except Exception as e:  # noqa: BLE001
        return Check("backend", False, f"local: Ollama unreachable ({str(e)[:60]})")
    want = config.backend.instruct_model
    ok = any(t.startswith(want) for t in tags)
    return Check("backend", ok, f"local: {want} {'present' if ok else 'not pulled'}")


def _check_embeddings(config: Config) -> Check:
    try:
        tags = _ollama_tags(config)
    except Exception as e:  # noqa: BLE001
        return Check("embeddings", False, f"Ollama unreachable ({str(e)[:60]})")
    want = config.backend.embed_model
    ok = any(t.startswith(want) for t in tags)
    return Check("embeddings", ok, f"{want} {'present' if ok else 'not pulled'}")


def _check_whisper(config: Config) -> Check:
    if importlib.util.find_spec("faster_whisper") is None:
        return Check("Whisper", False, "faster-whisper not installed")
    return Check(
        "Whisper", True, f"faster-whisper ({whisper_model_for(config.backend.profile)})"
    )


def _check_piper(config: Config) -> Check:
    have_engine = (
        importlib.util.find_spec("piper") is not None
        or config.voice.piper_bin
        or shutil.which("piper")
    )
    if not have_engine:
        return Check("Piper", False, "piper-tts not installed and no `piper` binary")
    voice = config.voice.resolved_voice_path
    if not voice.exists():
        return Check("Piper", False, f"voice model missing: {voice}")
    return Check("Piper", True, f"{config.voice.tts_voice}")


def _check_vram(config: Config) -> Check:
    try:
        import torch

        if not torch.cuda.is_available():
            return Check("VRAM", True, "no CUDA (CPU inference)")
        free, _total = torch.cuda.mem_get_info()
        free_gb = free / 1e9
        need = 5.5 if config.backend.profile == "quality" else 4.0
        ok = free_gb >= need
        return Check(
            "VRAM",
            ok,
            f"{free_gb:.1f} GB free (need ~{need} GB for {config.backend.profile})",
        )
    except Exception:
        return Check("VRAM", True, "no CUDA (CPU inference)")


_CHECKS = (
    _check_postgres,
    _check_pgvector,
    _check_backend,
    _check_embeddings,
    _check_whisper,
    _check_piper,
    _check_vram,
)


def run_checks(config: Config) -> list[Check]:
    return [fn(config) for fn in _CHECKS]


def format_report(checks: list[Check]) -> str:
    width = max((len(c.name) for c in checks), default=0)
    lines = []
    for c in checks:
        tag = "OK  " if c.ok else "FAIL"
        lines.append(f"{tag}  {c.name.ljust(width)}  {c.detail}")
    return "\n".join(lines)
