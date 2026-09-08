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
