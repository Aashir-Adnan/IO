from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

from io_assistant.config import Config

__all__ = ["BootstrapError", "db_reachable", "ensure_database", "project_root"]


class BootstrapError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def project_root() -> Path:
    """Where the bundled data lives — the one-dir bundle when frozen, else the
    repo root."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def _dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


def db_reachable(config: Config, timeout: float = 1.0) -> bool:
    try:
        import psycopg

        with psycopg.connect(_dsn(config.database_url),
                             connect_timeout=max(1, int(timeout))):
            return True
    except Exception:
        return False


def _alembic_upgrade(config: Config) -> None:
    from alembic import command
    from alembic.config import Config as AlembicConfig

    root = project_root()
    cfg = AlembicConfig(str(root / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(root / "io_assistant" / "db" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", config.database_url)
    command.upgrade(cfg, "head")


def ensure_database(config: Config, *, start_container: bool = True) -> None:
    """Make the database reachable and migrated. Raises BootstrapError with a
    user-facing message on any failure the user can act on."""
    if not db_reachable(config):
        if not start_container:
            raise BootstrapError("The database is not reachable.")
        if shutil.which("docker") is None:
            raise BootstrapError(
                "Docker Desktop isn't running. Start Docker Desktop, then "
                "reopen IO.")
        compose = project_root() / "docker-compose.yml"
        try:
            subprocess.run(
                ["docker", "compose", "-f", str(compose), "up", "-d", "db"],
                check=True, capture_output=True, text=True, timeout=180)
        except Exception as e:  # noqa: BLE001
            detail = getattr(e, "stderr", "") or str(e)
            raise BootstrapError(
                f"Couldn't start the database container.\n\n{detail}") from e
        for _ in range(60):
            if db_reachable(config):
                break
            time.sleep(1)
        else:
            raise BootstrapError("The database container did not become ready.")
    _alembic_upgrade(config)
