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
from collections import Counter

import pytest

from harness.tasks import DIFFICULTIES, LANGUAGES, load_task, task_ids
from scripts.validate_tasks import changed_task_ids, check_host, validate


def selected_tasks() -> list[str]:
    if os.environ.get("EVALH_E1_TASKS") == "all":
        return task_ids()
    return changed_task_ids(os.environ.get("EVALH_BASE_REF", "origin/main"))


def test_the_bank_has_10_tasks_with_3_per_level_and_2_per_language() -> None:
    """phases.md P3-6 (D24, D55): at least 10 tasks, at least 3 of each difficulty level and at
    least 2 of each language. Minimums, so the test keeps holding as the bank grows."""
    tasks = [load_task(task_id) for task_id in task_ids()]
    assert len(tasks) >= 10
    levels = Counter(t.difficulty for t in tasks)
    languages = Counter(t.language for t in tasks)
    assert all(levels[level] >= 3 for level in DIFFICULTIES), levels
    assert all(languages[language] >= 2 for language in LANGUAGES), languages


def test_the_bank_has_15_tasks_in_the_phase_4_mix() -> None:
    """phases.md P4-7 (D24, D62): at least 15 tasks, with at least 5 easy, 6 medium and 4 hard,
    and at least 7 Python, 4 Go and 4 Rust. Minimums, so the test keeps holding in Phase 5."""
    tasks = [load_task(task_id) for task_id in task_ids()]
    assert len(tasks) >= 15
    levels = Counter(t.difficulty for t in tasks)
    languages = Counter(t.language for t in tasks)
    assert all(levels[k] >= n for k, n in {"easy": 5, "medium": 6, "hard": 4}.items()), levels
    assert all(languages[k] >= n for k, n in {"python": 7, "go": 4, "rust": 4}.items()), languages


def test_every_task_passes_the_host_rules() -> None:
    problems = {task_id: check_host(task_id)[1].problems() for task_id in task_ids()}
    assert problems == {task_id: [] for task_id in task_ids()}


@pytest.mark.docker
def test_the_selected_tasks_pass_full_validation(docker_engine: None) -> None:
    # The validator prints a line per task and rule (shown with `pytest -s`).
    failed = {task_id: problems for task_id in selected_tasks() if (problems := validate(task_id))}
    assert failed == {}
