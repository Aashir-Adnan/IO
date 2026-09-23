from pathlib import Path
import textwrap
import pytest
from io_assistant.config import load_config, ConfigError

def write_toml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(textwrap.dedent(body))
    return p

def test_loads_defaults(tmp_path):
    p = write_toml(tmp_path, """
        database_url = "postgresql+psycopg://u:p@localhost/db"
        embedding_dim = 768
        [backend]
        provider = "local"
        profile = "light"
        anthropic_model = "claude-haiku-4-5"
        ollama_url = "http://localhost:11434"
        ollama_keep_alive = "30s"
        instruct_model = "llama3.2:3b"
        embed_model = "nomic-embed-text"
        num_thread = 0
        [resolver]
        fuzzy_threshold = 92
        vector_similarity_threshold = 0.85
        confidence_gate_threshold = 0.6
    """)
    cfg = load_config(p)
    assert cfg.backend.provider == "local"
    assert cfg.resolver.fuzzy_threshold == 92
    assert cfg.embedding_dim == 768

def test_light_profile_sets_instruct_model(tmp_path):
    p = write_toml(tmp_path, """
        database_url = "postgresql+psycopg://u:p@localhost/db"
        embedding_dim = 768
        [backend]
        provider = "local"
        profile = "light"
        anthropic_model = "claude-haiku-4-5"
        ollama_url = "http://localhost:11434"
        ollama_keep_alive = "30s"
        instruct_model = "IGNORED"
        embed_model = "nomic-embed-text"
        num_thread = 0
        [resolver]
        fuzzy_threshold = 92
        vector_similarity_threshold = 0.85
        confidence_gate_threshold = 0.6
    """)
    cfg = load_config(p)
    assert cfg.backend.instruct_model == "llama3.2:3b"   # light profile default

def test_invalid_provider_raises(tmp_path):
    p = write_toml(tmp_path, """
        database_url = "x"
        embedding_dim = 768
        [backend]
        provider = "banana"
        profile = "light"
        anthropic_model = "claude-haiku-4-5"
        ollama_url = "http://localhost:11434"
        ollama_keep_alive = "30s"
        instruct_model = "llama3.2:3b"
        embed_model = "nomic-embed-text"
        num_thread = 0
        [resolver]
        fuzzy_threshold = 92
        vector_similarity_threshold = 0.85
        confidence_gate_threshold = 0.6
    """)
    with pytest.raises(ConfigError):
        load_config(p)

def test_env_overrides_database_url(tmp_path, monkeypatch):
    monkeypatch.setenv("IO_DATABASE_URL", "postgresql+psycopg://env@localhost/envdb")
    p = write_toml(tmp_path, """
        database_url = "postgresql+psycopg://file@localhost/filedb"
        embedding_dim = 768
        [backend]
        provider = "local"
        profile = "light"
        anthropic_model = "claude-haiku-4-5"
        ollama_url = "http://localhost:11434"
        ollama_keep_alive = "30s"
        instruct_model = "llama3.2:3b"
        embed_model = "nomic-embed-text"
        num_thread = 0
        [resolver]
        fuzzy_threshold = 92
        vector_similarity_threshold = 0.85
        confidence_gate_threshold = 0.6
    """)
    cfg = load_config(p)
    assert cfg.database_url == "postgresql+psycopg://env@localhost/envdb"

def test_embedding_dim_must_match_orm(tmp_path):
    p = write_toml(tmp_path, """
        database_url = "postgresql+psycopg://u:p@localhost/db"
        embedding_dim = 512
        [backend]
        provider = "local"
        profile = "light"
        anthropic_model = "claude-haiku-4-5"
        ollama_url = "http://localhost:11434"
        ollama_keep_alive = "30s"
        instruct_model = "llama3.2:3b"
        embed_model = "nomic-embed-text"
        num_thread = 0
        [resolver]
        fuzzy_threshold = 92
        vector_similarity_threshold = 0.85
        confidence_gate_threshold = 0.6
    """)
    with pytest.raises(ConfigError, match="embedding_dim"):
        load_config(p)

def test_service_section_defaults(tmp_path):
    p = write_toml(tmp_path, """
        database_url = "postgresql+psycopg://u:p@localhost/db"
        embedding_dim = 768
        [backend]
        provider = "local"
        profile = "light"
        anthropic_model = "claude-haiku-4-5"
        ollama_url = "http://localhost:11434"
        ollama_keep_alive = "30s"
        instruct_model = "llama3.2:3b"
        embed_model = "nomic-embed-text"
        num_thread = 0
        [resolver]
        fuzzy_threshold = 92
        vector_similarity_threshold = 0.85
        confidence_gate_threshold = 0.6
    """)
    cfg = load_config(p)
    assert cfg.service.host == "127.0.0.1"
    assert cfg.service.port == 8765

def test_voice_and_capture_defaults(tmp_path):
    p = write_toml(tmp_path, """
        database_url = "postgresql+psycopg://u:p@localhost/db"
        embedding_dim = 768
        [backend]
        provider = "local"
        profile = "light"
        anthropic_model = "claude-haiku-4-5"
        ollama_url = "http://localhost:11434"
        ollama_keep_alive = "30s"
        instruct_model = "llama3.2:3b"
        embed_model = "nomic-embed-text"
        num_thread = 0
        [resolver]
        fuzzy_threshold = 92
        vector_similarity_threshold = 0.85
        confidence_gate_threshold = 0.6
    """)
    cfg = load_config(p)
    assert cfg.voice.tts_voice == "en_US-hfc_female-medium"
    assert cfg.capture.passive is False
    from io_assistant.config import whisper_model_for
    assert whisper_model_for("light") == "base"
    assert whisper_model_for("quality") == "small"


def test_load_config_prefers_user_config(tmp_path, monkeypatch):
    good = (Path(__file__).resolve().parents[1] / "config.toml").read_text()
    user_dir = tmp_path / "userhome" / ".config" / "io"
    user_dir.mkdir(parents=True)
    (user_dir / "config.toml").write_text(good)

    real_expand = __import__("os.path", fromlist=["expanduser"]).expanduser
    monkeypatch.setattr(
        "os.path.expanduser",
        lambda p: p.replace("~", str(tmp_path / "userhome"), 1)
        if p.startswith("~") else real_expand(p))
    monkeypatch.chdir(tmp_path)  # no ./config.toml here
    cfg = load_config()
    assert cfg.embedding_dim == 768


_BASE = """
    database_url = "postgresql+psycopg://u:p@localhost/db"
    embedding_dim = 768
    [backend]
    provider = "local"
    profile = "light"
    anthropic_model = "claude-haiku-4-5"
    ollama_url = "http://localhost:11434"
    ollama_keep_alive = "30s"
    instruct_model = "llama3.2:3b"
    embed_model = "nomic-embed-text"
    num_thread = 0
    [resolver]
    fuzzy_threshold = 92
    vector_similarity_threshold = 0.85
    confidence_gate_threshold = 0.6
"""


def test_updates_defaults(tmp_path):
    cfg = load_config(write_toml(tmp_path, _BASE))
    assert cfg.updates.enabled is True
    assert cfg.updates.branch == "" and cfg.updates.interval_h == 6.0


def test_local_override_is_deep_merged(tmp_path):
    p = write_toml(tmp_path, _BASE)
    (tmp_path / "config.local.toml").write_text(textwrap.dedent("""
        [backend]
        provider = "anthropic"
        [updates]
        interval_h = 2
    """))
    cfg = load_config(p)
    assert cfg.backend.provider == "anthropic"            # overridden
    assert cfg.backend.embed_model == "nomic-embed-text"  # sibling key kept
    assert cfg.resolver.fuzzy_threshold == 92             # other table untouched
    assert cfg.updates.interval_h == 2


def test_missing_local_override_is_fine(tmp_path):
    assert load_config(write_toml(tmp_path, _BASE)).backend.provider == "local"


def test_invalid_local_override_names_the_file(tmp_path):
    p = write_toml(tmp_path, _BASE)
    (tmp_path / "config.local.toml").write_text("this is = = not toml")
    with pytest.raises(ConfigError, match="config.local.toml"):
        load_config(p)
