import shutil
import subprocess
from pathlib import Path

import pytest

from io_assistant.updates.check import check

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git not installed")


def git(cwd, *args):
    subprocess.run(
        [GIT, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
         *args], cwd=cwd, check=True, capture_output=True, text=True)


def commit(repo: Path, name: str, msg: str):
    (repo / name).write_text(msg)
    git(repo, "add", name)
    git(repo, "commit", "-m", msg)


@pytest.fixture
def repos(tmp_path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    work = tmp_path / "work"
    git(tmp_path, "clone", str(remote), str(work))
    commit(work, "a.txt", "first")
    git(work, "push", "-u", "origin", "main")
    other = tmp_path / "other"
    git(tmp_path, "clone", str(remote), str(other))
    return remote, work, other


def test_up_to_date(repos):
    _, work, _ = repos
    s = check(work)
    assert s.error is None and not s.available and s.behind == 0
    assert s.branch == "main" and s.sha


def test_behind_lists_subjects_newest_first(repos):
    _, work, other = repos
    commit(other, "b.txt", "add widgets")
    commit(other, "c.txt", "fix status")
    git(other, "push", "origin", "main")
    s = check(work)
    assert s.available and s.behind == 2
    assert s.subjects == ["fix status", "add widgets"]


def test_tracked_change_is_dirty_untracked_is_not(repos):
    _, work, _ = repos
    (work / "new.txt").write_text("untracked")
    assert check(work).dirty is False
    (work / "a.txt").write_text("edited")
    assert check(work).dirty is True


def test_unreachable_remote_is_an_error_not_an_exception(repos):
    remote, work, _ = repos
    git(work, "remote", "set-url", "origin", str(remote.parent / "gone.git"))
    s = check(work)
    assert s.error and not s.available


def test_branch_without_remote_counterpart_reports_no_update(repos):
    _, work, _ = repos
    git(work, "checkout", "-b", "local-only")
    s = check(work)
    assert not s.available and s.branch == "local-only"


def test_explicit_branch_compares_against_that_remote_branch(repos):
    _, work, other = repos
    commit(other, "b.txt", "upstream change")
    git(other, "push", "origin", "main")
    git(work, "checkout", "-b", "feature")
    s = check(work, branch="main")
    assert s.available and s.behind == 1
