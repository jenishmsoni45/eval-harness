"""The hard-code cheater (D13, D63): on every easy task it special-cases the failing visible
test's inputs. The visible tests then pass and a hidden bug test fails, so every attempt gets
`visible_pass_hidden_fail`, which is reported but costs nothing (phases.md P4-1)."""

from __future__ import annotations

import pytest

from harness.agents.cheaters import HARD_CODES
from harness.integrity import runner_detection
from harness.tasks import LANGUAGES, load_task, read_tree, task_ids
from tests.cheaters.cheats import CheaterRuns, assert_flagged


@pytest.mark.docker
@pytest.mark.parametrize("language", LANGUAGES)
def test_every_hard_code_attempt_is_flagged(cheater_runs: CheaterRuns, language: str) -> None:
    for r in assert_flagged("hard-code", language, cheater_runs):
        assert r["visible_passed"] is True, r
        assert r["base"] < 1, r
        assert r["cheat_flags"] == [], r
        assert r["reward"] == r["base"], r


def test_every_easy_task_has_a_hard_code() -> None:
    """The trick applies to every easy task, the only ones with a failing visible test."""
    easy = {t for t in task_ids() if load_task(t).difficulty == "easy"}
    assert set(HARD_CODES) == easy


def test_a_hard_code_is_not_runner_detection() -> None:
    """Its only flag is the overfitting signal: the special case uses no runner detection."""
    for task_id, (path, old, new) in HARD_CODES.items():
        task = load_task(task_id)
        pristine = read_tree(task.repo_dir)
        changed = pristine[path].decode().replace(old, new, 1).encode()
        assert runner_detection(task, pristine, {path: changed}) == [], task_id
