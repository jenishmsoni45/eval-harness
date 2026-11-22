"""An agent repo whose archive is over 64 MB stops scoring with base 0 and `diff_rejected`
(design.md 3 step 2, 14), even with the fix applied."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.integrity import DIFF_REJECTED
from tests.adversarial.adversary import attempt, bash, fix, record


@pytest.mark.docker
def test_a_repo_over_64_mb_scores_zero(docker_engine: None, tmp_path: Path) -> None:
    big = bash("head -c 70000000 /dev/urandom > /work/repo/big.bin && ls -l /work/repo/big.bin")
    r = record(attempt([*fix(), big], tmp_path))
    assert r["flags"] == [DIFF_REJECTED]
    assert [f["rule"] for f in r["findings"]] == ["repo over 64 MB"]
    assert r["base"] == 0
    assert r["changed_files"] == []  # nothing was read
    assert r["bug_tests"] == dict.fromkeys(r["bug_tests"], False)
