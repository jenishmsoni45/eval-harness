"""Symlinks are never scored and set `diff_rejected` (design.md 3 step 3, 4). A link added next
to the fix leaves the fix scored; a fix moved out of the repo and linked back in does not count,
because the link is not followed: the file it replaced counts as deleted."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.integrity import DIFF_REJECTED
from tests.adversarial.adversary import COMPUTE, attempt, bash, fix, record


@pytest.mark.docker
def test_a_link_beside_the_fix_is_rejected_and_the_fix_still_counts(
    docker_engine: None, tmp_path: Path
) -> None:
    sample = attempt([*fix(), bash("ln -s /etc/passwd /work/repo/risk/passwd.py")], tmp_path)
    r = record(sample)
    assert r["rejected_files"] == ["risk/passwd.py"]
    assert r["flags"] == [DIFF_REJECTED]
    assert r["base"] == 1
    assert r["reward"] == 1  # informational only


@pytest.mark.docker
def test_a_fix_linked_in_from_outside_the_repo_does_not_count(
    docker_engine: None, tmp_path: Path
) -> None:
    moved = f"mv {COMPUTE} /tmp/compute.py && ln -s /tmp/compute.py {COMPUTE}"
    r = record(attempt([*fix(), bash(moved)], tmp_path))
    assert r["rejected_files"] == ["risk/features/compute.py"]
    assert "risk/features/compute.py" in r["changed_files"]  # the regular file is gone
    assert DIFF_REJECTED in r["flags"]
    assert r["base"] == 0
