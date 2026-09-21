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
    # "auto": one combined route+extract+plan call on anthropic/hybrid (and
    # local "quality"), the tuned two-step on local "light". "combined" /
    # "split" force it. Parse failure always falls back to split.
    decide: Literal["auto", "combined", "split"] = "auto"
    ollama_url: str
    ollama_keep_alive: str
    instruct_model: str
    embed_model: str
    num_thread: int
    # "auto": Ollama when reachable, else the in-process fastembed model (same
    # nomic-embed-text v1.5, 768-d, so vectors are interchangeable).
    embedder: Literal["auto", "ollama", "builtin"] = "auto"
    builtin_embed_model: str = "nomic-ai/nomic-embed-text-v1.5"
    models_dir: str = "~/.local/share/io/models"

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

    # Speech-to-text mode:
    #   "whisper"        local, batch — transcribes when you stop talking.
    #   "whisper-stream" local, real-time — a rolling faster-whisper loop emits
    #                    words + corrections as you speak. Loads a ~1.5 GB
    #                    model and pins the GPU during a call (best on a GPU;
    #                    on CPU it lags). Fully offline.
    #   "soniox"         cloud, real-time — needs SONIOX_API_KEY (see
    #                    rules/local-first.md). Falls back to "whisper" if unset.
    stt_provider: Literal["whisper", "whisper-stream", "soniox"] = "whisper"
    soniox_model: str = "stt-rt-v5"
    whisper_stream_model: str = "large-v3-turbo"

    @property
    def resolved_voice_path(self) -> Path:
        return Path(expanduser(self.voices_dir)) / f"{self.tts_voice}.onnx"

    @property
    def soniox_api_key(self) -> str | None:
        return os.environ.get("SONIOX_API_KEY") or None

    @property
    def stt_streaming(self) -> bool:
        if self.stt_provider == "whisper-stream":
            return True
        return self.stt_provider == "soniox" and bool(self.soniox_api_key)

class CaptureConfig(BaseModel):
    hotkey: str = "<ctrl>+<alt>+space"
    passive: bool = False
    sample_rate: int = 16000
    vad_aggressiveness: int = 2

class UiConfig(BaseModel):
    name: str = ""            # greeting name; "" -> the OS user at read time
    fullscreen: bool = True
    auto_speak: Literal["voice", "always", "never"] = "voice"
    typing_cps: int = 45
    min_think_ms: int = 600

class FilesConfig(BaseModel):
    enabled: bool = False
    allowlist_roots: list[str] = []
    max_file_bytes: int = 2_000_000
    index_extensions: list[str] = [
        ".txt", ".md", ".markdown", ".rst", ".pdf", ".docx", ".rtf",
        ".csv", ".tsv", ".json", ".yaml", ".yml", ".html", ".htm", ".xml", ".log",
        ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rb", ".rs",
        ".c", ".h", ".cpp", ".sh",
    ]
    media_extensions: list[str] = [
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".tiff",
        ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi",
    ]
    exclude_globs: list[str] = [
        "**/.git/**", "**/node_modules/**", "**/__pycache__/**", "**/.venv/**",
        "**/.env*", "**/*.env", "**/*.pem", "**/*.key", "**/id_rsa*",
        "**/*.kdbx", "**/*.ppk", "**/.ssh/**", "**/.aws/**", "**/.gnupg/**",
    ]
    chunk_tokens: int = 400
    chunk_overlap: int = 40
    max_chunks_per_file: int = 60
    max_files_per_registration: int = 5000
    retrieval_file_limit: int = 6
    follow_symlinks: bool = False
    thumbs_dir: str = "~/.local/share/io/thumbs"

class WebConfig(BaseModel):
    # Opt-in web-backed answers. Default engine is a self-hosted SearXNG in
    # IO's own Docker stack (localhost). A cloud provider is a deliberate
    # exception — see rules/local-first.md. enabled=false => general-knowledge
    # questions stay "unknown", exactly as before.
    enabled: bool = False
    provider: Literal["searxng", "none"] = "searxng"
    searxng_url: str = "http://localhost:8888"
    max_pages: int = 4
    fetch_bytes: int = 400_000
    news_ttl_min: int = 30
    fact_ttl_min: int = 360
    instant_ttl_min: int = 1440


class Config(BaseModel):
    database_url: str
    embedding_dim: int
    backend: BackendConfig
    resolver: ResolverConfig
    service: ServiceConfig = ServiceConfig()
    voice: VoiceConfig = VoiceConfig()
    capture: CaptureConfig = CaptureConfig()
    ui: UiConfig = UiConfig()
    files: FilesConfig = FilesConfig()
    web: WebConfig = WebConfig()

    @property
    def owner_name(self) -> str:
        """The user's own name — for resolving "me"/"I"/"my" in captions and
        queries. `ui.name`, else the OS user, else "" (no self tag)."""
        return (
            self.ui.name
            or os.environ.get("USERNAME")
            or os.environ.get("USER")
            or ""
        )

_WHISPER_BY_PROFILE = {"light": "base", "quality": "small"}

def whisper_model_for(profile: str) -> str:
    return _WHISPER_BY_PROFILE.get(profile, "base")

def _candidate_config_paths() -> list[Path]:
    return [
        Path("config.toml"),
        Path(os.path.expanduser("~/.config/io/config.toml")),
        Path(__file__).resolve().parent.parent / "config.toml",
    ]

def config_source(path: str | Path | None = None) -> Path:
    """The config.toml that load_config would read: explicit path, else the
    first of CWD / ~/.config/io / the bundled repo-root file that exists."""
    if path is not None:
        return Path(path)
    for p in _candidate_config_paths():
        if p.exists():
            return p
    return _candidate_config_paths()[-1]

def load_config(path: str | Path | None = None) -> Config:
    p = config_source(path)
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
