"""E1 (design.md 1; phases.md P2-3, P2-8): every task in the bank passes validation rules V1-V10,
V12 and V13: each bug test fails on the shipped bug, the reference fix passes every test, and
the wrong and partial patches behave as described, in 5 of 5 fresh-container runs.

The host rules run for every task. The full validation, with Docker, runs for (D15, D43):
- every task, when EVALH_E1_TASKS=all (the "validate all" workflow);
- otherwise the tasks changed since EVALH_BASE_REF (default origin/main), as pull-request CI
  does, so a pull request validates only the tasks it changes.
"""

from __future__ import annotations

import os

import pytest

from harness.tasks import task_ids
from scripts.validate_tasks import changed_task_ids, check_host, validate


def selected_tasks() -> list[str]:
    if os.environ.get("EVALH_E1_TASKS") == "all":
        return task_ids()
    return changed_task_ids(os.environ.get("EVALH_BASE_REF", "origin/main"))


def test_every_task_passes_the_host_rules() -> None:
    problems = {task_id: check_host(task_id)[1].problems() for task_id in task_ids()}
    assert problems == {task_id: [] for task_id in task_ids()}


@pytest.mark.docker
def test_the_selected_tasks_pass_full_validation(docker_engine: None) -> None:
    # The validator prints a line per task and rule (shown with `pytest -s`).
    failed = {task_id: problems for task_id in selected_tasks() if (problems := validate(task_id))}
    assert failed == {}
