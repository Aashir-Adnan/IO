"""Move a user's edits to the tracked config.toml into the gitignored
config.local.toml so an update can change the shipped defaults without
clobbering them (load_config deep-merges local over the base)."""
from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path


def _diff(work: dict, head: dict) -> dict:
    """Keys of `work` that differ from (or are missing in) `head`."""
    out: dict = {}
    for k, v in work.items():
        if isinstance(v, dict) and isinstance(head.get(k), dict):
            d = _diff(v, head[k])
            if d:
                out[k] = d
        elif head.get(k) != v or k not in head:
            out[k] = v
    return out


def _scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v)          # a valid TOML basic string
    if isinstance(v, list):
        return "[" + ", ".join(_scalar(x) for x in v) + "]"
    raise TypeError(f"can't write {type(v).__name__} to TOML")


def dump_toml(d: dict, _prefix: str = "") -> str:
    """Minimal TOML writer: nested tables of scalars / lists of scalars."""
    lines = [f"{k} = {_scalar(v)}" for k, v in d.items() if not isinstance(v, dict)]
    out = "\n".join(lines) + ("\n" if lines else "")
    for k, v in d.items():
        if isinstance(v, dict):
            name = f"{_prefix}{k}"
            out += f"\n[{name}]\n" + dump_toml(v, name + ".")
    return out


def split_local(repo: Path) -> dict:
    """Write config.local.toml with the user's edits and restore the tracked
    file. No-op (returns {}) if nothing changed or a local file already exists."""
    cfg, local = repo / "config.toml", repo / "config.local.toml"
    if local.exists() or not cfg.exists():
        return {}
    r = subprocess.run(["git", "show", "HEAD:config.toml"], cwd=repo,
                       capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    diff = _diff(tomllib.loads(cfg.read_text()), tomllib.loads(r.stdout))
    if not diff:
        return {}
    local.write_text(dump_toml(diff))
    subprocess.run(["git", "checkout", "--", "config.toml"], cwd=repo, check=True,
                   capture_output=True)
    return diff
