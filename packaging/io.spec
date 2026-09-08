# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-dir spec for IO.

Build:  uv run pyinstaller packaging/io.spec --noconfirm
Output: dist/IO/IO.exe  (one-dir bundle)

Not bundled: PostgreSQL (expects Docker / a user database_url) and the
Whisper/Piper models (download at first use to ~/.local/share/io).
"""
from pathlib import Path

try:
    ROOT = Path(SPECPATH).resolve().parent  # SPECPATH is injected by PyInstaller
except NameError:  # imported by the test via runpy, not by PyInstaller
    ROOT = Path(__file__).resolve().parent.parent

ENTRY = "io_assistant/app_entry.py"

# (repo-relative source, bundle-relative dest)
DATAS = [
    ("frontend", "frontend"),
    ("config.toml", "."),
    ("alembic.ini", "."),
    ("io_assistant/db/migrations", "io_assistant/db/migrations"),
    ("io_assistant/prompts", "io_assistant/prompts"),
    ("assets/io-512.png", "assets"),
]

HIDDEN_IMPORTS = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "pgvector.sqlalchemy",
    "psycopg",
    "psycopg_binary",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "pypdf",
    "docx",
    "PIL.Image",
]

# The Task-5 test imports this file with run_name="__spec_probe__" and reads
# only ENTRY / DATAS. Analysis/PYZ/EXE/COLLECT exist only inside PyInstaller.
if __name__ != "__spec_probe__":
    a = Analysis(
        [str(ROOT / ENTRY)],
        pathex=[str(ROOT)],
        binaries=[],
        datas=[(str(ROOT / s), d) for s, d in DATAS],
        hiddenimports=HIDDEN_IMPORTS,
        hookspath=[],
        runtime_hooks=[],
        excludes=["reportlab", "pytest"],
        noarchive=False,
    )
    pyz = PYZ(a.pure)
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="IO",
        console=False,
        icon=str(ROOT / "assets" / "io.ico"),
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="IO")
