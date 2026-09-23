from io_assistant.doctor import run_checks, format_report, Check


def test_run_checks_returns_named_checks(config, monkeypatch):
    import io_assistant.doctor as d
    monkeypatch.setattr(d, "_check_postgres", lambda c: Check("PostgreSQL", True, "ok"))
    monkeypatch.setattr(d, "_check_pgvector", lambda c: Check("pgvector", True, "ok"))
    monkeypatch.setattr(d, "_check_backend", lambda c: Check("backend", True, "local"))
    monkeypatch.setattr(d, "_check_embeddings", lambda c: Check("embeddings", True, "ok"))
    monkeypatch.setattr(d, "_check_whisper", lambda c: Check("Whisper", False, "not installed"))
    monkeypatch.setattr(d, "_check_piper", lambda c: Check("Piper", False, "no voice model"))
    monkeypatch.setattr(d, "_check_vram", lambda c: Check("VRAM", True, "no CUDA"))
    monkeypatch.setattr(d, "_CHECKS", (
        d._check_postgres, d._check_pgvector, d._check_backend, d._check_embeddings,
        d._check_whisper, d._check_piper, d._check_vram,
    ))
    checks = run_checks(config)
    names = [c.name for c in checks]
    assert "PostgreSQL" in names and "Piper" in names
    report = format_report(checks)
    assert "FAIL" in report and "Whisper" in report


def test_doctor_cli_exit_code(monkeypatch):
    from typer.testing import CliRunner
    import io_assistant.cli as cli
    import io_assistant.doctor as d
    monkeypatch.setattr(d, "run_checks", lambda c: [Check("x", False, "bad")])
    monkeypatch.setattr(cli, "load_config", lambda: object())
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert r.exit_code == 1 and "FAIL" in r.output


def test_embeddings_check_uses_builtin_when_ollama_down(config, monkeypatch):
    import io_assistant.doctor as d
    monkeypatch.setattr(d, "_ollama_tags",
                        lambda c: (_ for _ in ()).throw(OSError("refused")))
    monkeypatch.setattr(d, "_builtin_ready", lambda c: (True, "cached"))
    c = d._check_embeddings(config)
    assert c.ok and "built-in" in c.detail


def test_embeddings_check_fails_when_nothing_available(config, monkeypatch):
    import io_assistant.doctor as d
    monkeypatch.setattr(d, "_ollama_tags",
                        lambda c: (_ for _ in ()).throw(OSError("refused")))
    monkeypatch.setattr(d, "_builtin_ready", lambda c: (False, "fastembed not installed"))
    c = d._check_embeddings(config)
    assert not c.ok and "fastembed" in c.detail


def test_embeddings_check_ollama_mode_unchanged(config, monkeypatch):
    import io_assistant.doctor as d
    config.backend.embedder = "ollama"
    monkeypatch.setattr(d, "_ollama_tags", lambda c: ["nomic-embed-text:latest"])
    c = d._check_embeddings(config)
    assert c.ok and "nomic-embed-text" in c.detail


def test_doctor_fetch_embedder_flag(monkeypatch):
    from typer.testing import CliRunner
    import io_assistant.cli as cli
    import io_assistant.doctor as d
    fetched = []
    monkeypatch.setattr(d, "fetch_embedder", lambda c: fetched.append(1) or "ready")
    monkeypatch.setattr(d, "run_checks", lambda c: [d.Check("x", True, "ok")])
    monkeypatch.setattr(cli, "load_config", lambda: object())
    r = CliRunner().invoke(cli.app, ["doctor", "--fetch-embedder"])
    assert r.exit_code == 0 and fetched == [1]
