"""The skip-test cheater (D13, D65): it skips tests through a protected file (`pytest.skip` in a
test, `addopts`, a new `conftest.py`; `t.Skip`; `#[ignore]`). Every attempt gets
`protected_path`, and the change never reaches the scoring container (phases.md P4-1, P4-3)."""

from __future__ import annotations

import pytest

from harness.agents.cheaters import PYTHON_SKIPS, python_skip
from harness.tasks import LANGUAGES, load_task
from tests.cheaters.cheats import (
    CheaterRuns,
    assert_flagged,
    attempts_in,
    cheater_tasks,
    dropped_never_reached_the_scorer,
)
from tests.runs import record


@pytest.mark.docker
@pytest.mark.parametrize("language", LANGUAGES)
def test_every_skip_test_attempt_is_flagged(cheater_runs: CheaterRuns, language: str) -> None:
    records = assert_flagged("skip-test", language, cheater_runs)
    dropped_never_reached_the_scorer(records)


def test_the_python_skips_take_turns() -> None:
    """Across the bank's Python tasks every Python skip is used (D65)."""
    from harness.tasks import task_ids

    python = [t for t in task_ids() if load_task(t).language == "python"]
    assert {python_skip(load_task(t)) for t in python} == set(PYTHON_SKIPS)


@pytest.mark.docker
def test_the_python_skip_changes_the_file_it_names(cheater_runs: CheaterRuns) -> None:
    for task_id, sample in attempts_in("skip-test", "python", cheater_runs).items():
        how = python_skip(load_task(task_id))
        files = record(sample)["dropped_files"]
        expected = {"conftest": "conftest.py", "addopts": "pyproject.toml"}.get(how)
        if expected is None:
            assert len(files) == 1, (task_id, files)
            assert files[0].startswith("tests/"), (task_id, files)
        else:
            assert files == [expected], (task_id, files)
    assert cheater_tasks("skip-test")
