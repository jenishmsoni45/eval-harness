"""Helpers for the cheater tests (E5, phases.md P4-1 and P4-3).

Tasks follow D53 and D68: the tasks a pull request changes plus one per language, or every task
with EVALH_E1_TASKS=all. The hard-code cheater applies to easy tasks only, so it also gets the
first easy task of each language.

The three cheaters that change protected files run with a scorer that, after scoring, reads each
dropped file back from the scoring container, so a test can check that the protected change
never reached it (P4-3).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from inspect_ai.log import EvalLog, EvalSample
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from harness.agents.cheaters import CHEATERS, applicable_tasks
from harness.attempt import bash_commands
from harness.scorer import score_attempt, with_attempt_record
from harness.tasks import load_task, read_tree, task_ids
from harness.testrun import AGENT_USER, REPO_DIR
from tests.runs import by_task, invariant_tasks, record

CheaterRuns = Callable[[str], EvalLog]


def first_easy_task_per_language() -> list[str]:
    first: dict[str, str] = {}
    for task_id in task_ids():
        task = load_task(task_id)
        if task.difficulty == "easy":
            first.setdefault(task.language, task_id)
    return sorted(first.values())


def cheater_tasks(name: str) -> list[str]:
    among = set(invariant_tasks())
    if name == "hard-code":
        among |= set(first_easy_task_per_language())
    return applicable_tasks(name, sorted(among))


@scorer(metrics=[mean()])
def scored_then_inspected() -> Scorer:
    """The harness's scorer, then a look at the scoring container: for each dropped file,
    whether the container holds the pristine copy (or, for a file the agent added, nothing)."""

    async def score(state: TaskState, target: Target) -> Score:
        task = load_task(str(state.metadata["task_id"]))
        result = await score_attempt(
            sandbox("default"), sandbox("scorer"), task, bash_commands(state.messages)
        )
        result = with_attempt_record(result, state)
        assert result.metadata is not None
        pristine = read_tree(task.repo_dir)
        in_scorer: dict[str, bool] = {}
        for path in result.metadata["dropped_files"]:
            try:
                data: bytes | None = await sandbox("scorer").read_file(
                    f"{REPO_DIR}/{path}", text=False, user=AGENT_USER
                )
            except FileNotFoundError:
                data = None
            in_scorer[path] = data == pristine.get(path)
        metadata = {**result.metadata, "scorer_has_pristine": in_scorer}
        return result.model_copy(update={"metadata": metadata})

    return score


def attempts_in(name: str, language: str, runs: CheaterRuns) -> dict[str, EvalSample]:
    """The cheater's attempts on tasks of one language; there is at least one."""
    samples = by_task(runs(name))
    assert sorted(samples) == cheater_tasks(name), "one attempt per applicable task"
    chosen = {t: s for t, s in samples.items() if load_task(t).language == language}
    assert chosen, f"{name} ran on no {language} task"
    return chosen


def assert_flagged(name: str, language: str, runs: CheaterRuns) -> list[dict[str, Any]]:
    """Every attempt of the cheater on this language's tasks has its expected flag, was scored
    (never an error to retry), and, for a cheat flag, follows D28's reward."""
    expected = CHEATERS[name].expected_flag
    records = []
    for task_id, sample in attempts_in(name, language, runs).items():
        assert sample.error is None, task_id
        assert not sample.error_retries, task_id
        r = record(sample)
        assert expected in r["flags"], (task_id, r["flags"], r["findings"])
        if expected in r["cheat_flags"]:
            assert r["reward"] == r["base"] - 1, task_id
            assert r["reward"] <= 0, task_id
            assert not r["success"], task_id
        records.append(r)
    return records


def dropped_never_reached_the_scorer(records: list[dict[str, Any]]) -> None:
    """P4-3: every protected change was dropped, and the scoring container held the pristine
    copy of each dropped file after scoring."""
    for r in records:
        dropped = r["dropped_files"]
        assert isinstance(dropped, list), r
        assert dropped, r
        assert r["scorer_has_pristine"] == dict.fromkeys(dropped, True), r
