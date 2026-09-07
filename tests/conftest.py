import pytest
from io_assistant.config import Config, BackendConfig, ResolverConfig

@pytest.fixture
def config() -> Config:
    return Config(
        database_url="postgresql+psycopg://io:io@localhost:5432/io_test",
        embedding_dim=768,
        backend=BackendConfig(
            provider="local", profile="light",
            anthropic_model="claude-haiku-4-5",
            ollama_url="http://localhost:11434", ollama_keep_alive="30s",
            instruct_model="llama3.2:3b", embed_model="nomic-embed-text",
            num_thread=0,
        ),
        resolver=ResolverConfig(
            fuzzy_threshold=92, vector_similarity_threshold=0.85,
            confidence_gate_threshold=0.6,
        ),
    )
