"""`.git` is ignored: changes are found by comparing with the host's pristine snapshot, so an
agent that hides its changes from git, plants files in `.git` or deletes it changes nothing about
what is scored (design.md 3 step 3, 5 table)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.adversarial.adversary import attempt, bash, fix, record

HIDE_FROM_GIT = (
    "cd /work/repo && git update-index --assume-unchanged risk/features/compute.py && "
    "echo planted > .git/evil && mkdir -p .git/hooks && echo 'exit 0' > .git/hooks/pre-commit "
    "&& git status --short && git diff --stat"
)


@pytest.mark.docker
def test_a_fix_hidden_from_git_is_still_found(docker_engine: None, tmp_path: Path) -> None:
    r = record(attempt([*fix(), bash(HIDE_FROM_GIT)], tmp_path))
    assert r["changed_files"] == ["risk/features/compute.py"]
    assert r["flags"] == []
    assert r["base"] == 1


@pytest.mark.docker
def test_deleting_git_changes_nothing_scored(docker_engine: None, tmp_path: Path) -> None:
    r = record(attempt([*fix(), bash("rm -rf /work/repo/.git && ls -a /work/repo")], tmp_path))
    assert r["changed_files"] == ["risk/features/compute.py"]
    assert r["base"] == 1
