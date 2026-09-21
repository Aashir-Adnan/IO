"""Is there a newer commit on the git remote? Plain `git` only: no GitHub API,
no token stored by IO (private repos work through the user's own git
credentials). The one sanctioned outbound call is `git fetch` — see
rules/local-first.md, case 7."""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from io_assistant.config import Config


@dataclass
class UpdateStatus:
    available: bool = False
    behind: int = 0
    subjects: list[str] = field(default_factory=list)
    dirty: bool = False
    branch: str = ""
    sha: str = ""
    error: str | None = None
    checked_at: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def find_repo(config: Config) -> Path | None:
    """The git checkout IO updates: `[updates].repo_dir`, else the source tree
    this package lives in, else the CWD (how the packaged exe is launched)."""
    candidates = [Path(config.updates.repo_dir)] if config.updates.repo_dir else []
    candidates += [Path(__file__).resolve().parents[2], Path.cwd()]
    for c in candidates:
        if (c / ".git").exists():
            return c
    return None


def _git(repo: Path, *args: str, timeout: float) -> str:
    r = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout,
        # a credential prompt must never hang the service
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else "git failed")
    return r.stdout.strip()


def check(repo: Path, remote: str = "origin", branch: str = "",
          timeout: float = 15.0) -> UpdateStatus:
    """Fetch and compare HEAD with `<remote>/<branch>` (default: the current
    branch). Never raises; failures land in `.error`."""
    s = UpdateStatus(checked_at=time.time())
    try:
        s.branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD", timeout=timeout)
        s.sha = _git(repo, "rev-parse", "--short", "HEAD", timeout=timeout)
        s.dirty = bool(_git(repo, "status", "--porcelain", "--untracked-files=no",
                            timeout=timeout))
        _git(repo, "fetch", remote, timeout=timeout)
        target = f"{remote}/{branch or s.branch}"
        try:
            _git(repo, "rev-parse", "--verify", "--quiet", target, timeout=timeout)
        except RuntimeError:
            return s   # no remote counterpart (e.g. an unpushed branch): no update
        s.behind = int(_git(repo, "rev-list", "--count", f"HEAD..{target}", timeout=timeout))
        s.available = s.behind > 0
        if s.available:
            s.subjects = _git(repo, "log", "--format=%s", "-n", "20", f"HEAD..{target}",
                              timeout=timeout).splitlines()
    except Exception as e:  # noqa: BLE001 — timeouts, missing git, bad remote
        s.error = str(e) or type(e).__name__
        s.available = False
    return s
