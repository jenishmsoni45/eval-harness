"""Fork bombs and runaway processes (design.md 3 steps 1 and 6, 5 table, D61). None of them is an
error to retry:

- a fork bomb the agent leaves running is stopped before its repo is read, and the fix scores;
- processes the agent's code leaves behind under each test command are killed when the command
  ends, so the next one can start: here each test command leaves 100 detached sleepers, and the
  five commands (visible, three bug tests, regression) would fill the 256-PID limit without it;
- a fork bomb under the tests that starves pytest of CPU reaches the scoring limit (shortened to
  a few seconds here, D52), and every unfinished test counts as failed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.adversarial.adversary import COMPUTE, attempt, bash, edit, fix, record

BASH_BOMB = "(b() { b | b & }; b) >/dev/null 2>&1 & sleep 5; echo started"
FUTURE = "from __future__ import annotations\n"
SLEEPERS = (
    FUTURE
    + "\nimport subprocess as _subprocess\n\nfor _ in range(100):\n"
    + '    _subprocess.Popen(["sleep", "1000"], start_new_session=True)\n'
)
PYTHON_BOMB = (
    FUTURE
    + "\nimport os as _os\n\nif _os.fork() == 0:\n    while True:\n        try:\n"
    + "            _os.fork()\n        except OSError:\n            pass\n"
)


@pytest.mark.docker
def test_a_fork_bomb_left_running_is_stopped_and_the_fix_scored(
    docker_engine: None, tmp_path: Path
) -> None:
    r = record(attempt([*fix(), bash(BASH_BOMB)], tmp_path))
    assert r["processes_stopped"] > 0
    assert r["limits_hit"] == []
    assert r["base"] == 1


@pytest.mark.docker
def test_processes_left_by_each_test_command_are_killed_before_the_next(
    docker_engine: None, tmp_path: Path
) -> None:
    r = record(attempt([*fix(), edit(COMPUTE, FUTURE, SLEEPERS)], tmp_path))
    assert r["limits_hit"] == []
    assert r["processes_limit_hit"] is False
    assert r["visible_passed"] is True
    assert all(r["bug_tests"].values()), r["bug_tests"]
    assert r["regression_passed"] is True
    assert r["base"] == 1


@pytest.mark.docker
def test_a_fork_bomb_that_starves_the_tests_reaches_the_scoring_limit(
    docker_engine: None, tmp_path: Path
) -> None:
    r = record(attempt([*fix(), edit(COMPUTE, FUTURE, PYTHON_BOMB)], tmp_path, scoring_limit_s=20))
    assert r["limits_hit"] == ["scoring"]
    assert r["bug_tests"] == dict.fromkeys(r["bug_tests"], False)
    assert r["base"] == 0
