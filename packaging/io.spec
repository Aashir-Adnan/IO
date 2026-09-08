# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-dir spec for IO.

Build:  uv run pyinstaller packaging/io.spec --noconfirm
Output: dist/IO/IO.exe  (one-dir bundle)

Bundles every feature — text, files, media gallery, and voice. Not bundled:
PostgreSQL (the exe starts its own pgvector container via docker compose on
launch) and the Whisper/Piper model files (download at first use to
~/.local/share/io).
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
    ("docker-compose.yml", "."),
    ("scripts/initdb", "scripts/initdb"),
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

# voice — lazy-imported by `io listen` and the /voice route; bundle them so the
# packaged app is full-featured (models still download on first use).
_VOICE_HIDDEN = [
    "webrtcvad", "sounddevice", "pynput", "pynput.keyboard", "pynput.mouse",
    "faster_whisper", "ctranslate2", "onnxruntime", "av",
    "piper", "piper.voice", "piper.phonemize_espeak",
]

EXCLUDES = ["reportlab", "pytest", "pyinstaller", "torch"]
HOOKSPATH = [str(ROOT / "packaging" / "hooks")]

# The probe test imports this file with run_name="__spec_probe__" and reads only
# the module-level names above. Analysis/PYZ/EXE/COLLECT + PyInstaller.utils
# exist only inside a real PyInstaller run.
if __name__ != "__spec_probe__":
    from PyInstaller.utils.hooks import collect_all

    _binaries = []
    _datas = [(str(ROOT / s), d) for s, d in DATAS]
    _hidden = list(HIDDEN_IMPORTS) + list(_VOICE_HIDDEN)
    for pkg in ("piper", "faster_whisper", "sounddevice", "_sounddevice_data",
                "ctranslate2", "onnxruntime", "av"):
        d, b, h = collect_all(pkg)
        _datas += d
        _binaries += b
        _hidden += h

    a = Analysis(
        [str(ROOT / ENTRY)],
        pathex=[str(ROOT)],
        binaries=_binaries,
        datas=_datas,
        hiddenimports=_hidden,
        hookspath=HOOKSPATH,
        runtime_hooks=[],
        excludes=EXCLUDES,
        noarchive=False,
    )
    import os as _os

    pyz = PYZ(a.pure)
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="IO",
        console=_os.environ.get("IO_BUILD_CONSOLE") == "1",  # debug builds
        icon=str(ROOT / "assets" / "io.ico"),
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="IO")
