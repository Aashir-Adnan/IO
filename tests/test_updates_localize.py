import shutil
import subprocess
import textwrap
import tomllib

import pytest

from io_assistant.config import load_config
from io_assistant.updates.localize import dump_toml, split_local
from tests.test_config import _BASE

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git not installed")


def git(cwd, *args):
    subprocess.run([GIT, "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false", *args],
                   cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-b", "main")
    (tmp_path / "config.toml").write_text(textwrap.dedent(_BASE))
    git(tmp_path, "add", "config.toml")
    git(tmp_path, "commit", "-m", "defaults")
    return tmp_path


def test_edits_move_to_local_and_tracked_file_is_restored(repo):
    p = repo / "config.toml"
    edited = p.read_text().replace('provider = "local"', 'provider = "anthropic"') \
                          .replace("fuzzy_threshold = 92", "fuzzy_threshold = 90")
    p.write_text(edited)
    before = load_config(p)               # the user's effective settings
    diff = split_local(repo)
    assert diff == {"backend": {"provider": "anthropic"},
                    "resolver": {"fuzzy_threshold": 90}}
    local = tomllib.loads((repo / "config.local.toml").read_text())
    assert local == diff
    assert 'provider = "local"' in p.read_text()          # tracked file restored
    assert load_config(p) == before                        # same effective config


def test_unchanged_config_writes_nothing(repo):
    assert split_local(repo) == {}
    assert not (repo / "config.local.toml").exists()


def test_existing_local_file_is_never_overwritten(repo):
    (repo / "config.local.toml").write_text('[ui]\nname = "Keep"\n')
    p = repo / "config.toml"
    p.write_text(p.read_text().replace('provider = "local"', 'provider = "hybrid"'))
    assert split_local(repo) == {}
    assert (repo / "config.local.toml").read_text() == '[ui]\nname = "Keep"\n'
    assert 'provider = "hybrid"' in p.read_text()          # left as the user had it


def test_dump_toml_round_trips():
    d = {"top": 1, "backend": {"name": 'a "quoted" \ value', "on": True,
                               "ratio": 0.85, "roots": ["~/Docs", "~/Pics"]},
         "web": {"deep": {"x": 2}}}
    assert tomllib.loads(dump_toml(d)) == d
