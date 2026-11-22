"""Code that spins forever under the hidden tests reaches the scoring limit: the test running
then, and every later one, count as failed, and that is the agent's outcome, never an error to
retry (design.md 3 step 6, 5 table, D51). The limit runs at a few seconds here (D52)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.adversarial.adversary import COMPUTE, attempt, edit, fix, record

FUTURE = "from __future__ import annotations\n"


@pytest.mark.docker
def test_code_that_spins_under_the_tests_reaches_the_scoring_limit(
    docker_engine: None, tmp_path: Path
) -> None:
    spin = edit(COMPUTE, FUTURE, FUTURE + "\nwhile True:\n    pass\n")
    r = record(attempt([*fix(), spin], tmp_path, scoring_limit_s=15))
    assert r["limits_hit"] == ["scoring"]
    assert r["visible_passed"] is None
    assert r["bug_tests"] == dict.fromkeys(r["bug_tests"], False)
    assert r["base"] == 0
