from __future__ import annotations
import os
import tomllib
from os.path import expanduser
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ValidationError

class ConfigError(Exception):
    pass

PROFILE_DEFAULTS = {
    "light":   {"instruct_model": "llama3.2:3b",  "whisper_model": "base"},
    "quality": {"instruct_model": "qwen2.5:7b",   "whisper_model": "small"},
}

class BackendConfig(BaseModel):
    provider: Literal["local", "anthropic", "hybrid"]
    profile: Literal["light", "quality"]
    anthropic_model: str
    ollama_url: str
    ollama_keep_alive: str
    instruct_model: str
    embed_model: str
    num_thread: int

class ResolverConfig(BaseModel):
    fuzzy_threshold: int
    vector_similarity_threshold: float
    confidence_gate_threshold: float

class ServiceConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765
    frontend_dir: str | None = None

class VoiceConfig(BaseModel):
    tts_voice: str = "en_US-hfc_female-medium"
    voices_dir: str = "~/.local/share/io/piper"
    speak_in_app: bool = False
    piper_bin: str | None = None
    length_scale: float = 1.06
    noise_scale: float = 0.667
    noise_w_scale: float = 0.85

    @property
    def resolved_voice_path(self) -> Path:
        return Path(expanduser(self.voices_dir)) / f"{self.tts_voice}.onnx"

class CaptureConfig(BaseModel):
    hotkey: str = "<ctrl>+<alt>+space"
    passive: bool = False
    sample_rate: int = 16000
    vad_aggressiveness: int = 2

class Config(BaseModel):
    database_url: str
    embedding_dim: int
    backend: BackendConfig
    resolver: ResolverConfig
    service: ServiceConfig = ServiceConfig()
    voice: VoiceConfig = VoiceConfig()
    capture: CaptureConfig = CaptureConfig()

_WHISPER_BY_PROFILE = {"light": "base", "quality": "small"}

def whisper_model_for(profile: str) -> str:
    return _WHISPER_BY_PROFILE.get(profile, "base")

def _repo_root_config() -> Path:
    return Path(__file__).resolve().parent.parent / "config.toml"

def load_config(path: str | Path | None = None) -> Config:
    p = Path(path) if path is not None else _repo_root_config()
    if not p.exists():
        raise ConfigError(f"config file not found: {p}")
    try:
        raw = tomllib.loads(p.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML in {p}: {e}") from e

    # env overrides
    if env_db := os.environ.get("IO_DATABASE_URL"):
        raw["database_url"] = env_db

    # profile defaults override the file's instruct_model
    backend = raw.get("backend", {})
    profile = backend.get("profile")
    if profile in PROFILE_DEFAULTS:
        backend["instruct_model"] = PROFILE_DEFAULTS[profile]["instruct_model"]

    try:
        cfg = Config.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(str(e)) from e

    # The embedding dimension is fixed: the ORM/migration DDL is Vector(EMBED_DIM).
    # A mismatch otherwise surfaces only as an opaque pgvector insert failure.
    from io_assistant.db.models import EMBED_DIM

    if cfg.embedding_dim != EMBED_DIM:
        raise ConfigError(
            f"embedding_dim {cfg.embedding_dim} != db.models.EMBED_DIM "
            f"{EMBED_DIM}; changing the embedding dimension needs a migration "
            f"+ backfill (see .claude/rules/migrations.md)"
        )
    return cfg
