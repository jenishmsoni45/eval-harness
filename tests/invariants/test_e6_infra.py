"""E6 (design.md 1 and 8, D18; phases.md P5-2): an attempt hit by an injected infrastructure
failure is retried with the same seed, and its final record (outcome, reward, flags) equals that
of an uninjected run with that seed; an attempt that fails 3 times is excluded and never scored as
an agent failure. Also E4 across a retry: the retry starts from a clean filesystem.

The faults are real (tests/faults.py): the sandbox's start fails, or the agent's container is
killed from the host mid-attempt. Run on one task per language (D15).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from inspect_ai.log import EvalSample
from inspect_ai.model import Model, ModelOutput

from harness.agents.honest import honest_model
from harness.agents.scripted import Turn, scripted_model, submit, tool_call
from harness.eval import run_eval
from stats import report
from tests.faults import (
    ALWAYS,
    CONTAINER_GONE,
    START_FAILURE,
    failing_starts,
    kill_own_agent_container,
    killing_model,
)
from tests.invariants.test_e4_clean_fs import (
    check,
    leave,
    parse_check,
    pristine_tree_hash,
)
from tests.runs import bash_outputs, by_task, one_task_per_language, record

AGENT = "mid"
MASTER_SEED = 20261124
# What must be the same after a retry: the drawn outcome and seed, and everything scored.
SAME = (
    "agent",
    "base",
    "reward",
    "success",
    "flags",
    "cheat_flags",
    "visible_passed",
    "bug_tests",
    "regression_passed",
    "changed_files",
    "tool_calls",
)


def scored(sample: EvalSample) -> dict[str, Any]:
    r = record(sample)
    return {key: r[key] for key in SAME}


@pytest.fixture(scope="module")
def uninjected(
    docker_engine: None, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, EvalSample]:
    log = run_eval(
        honest_model(AGENT, master_seed=MASTER_SEED),
        task_ids=one_task_per_language(),
        log_dir=str(tmp_path_factory.mktemp("uninjected")),
    )
    samples = by_task(log)
    assert all(not s.error_retries for s in samples.values())
    return samples


@pytest.mark.docker
def test_a_container_that_fails_to_start_once_is_retried_with_the_same_seed(
    uninjected: dict[str, EvalSample], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with failing_starts(monkeypatch, times=1) as injected:
        log = run_eval(
            honest_model(AGENT, master_seed=MASTER_SEED),
            task_ids=one_task_per_language(),
            log_dir=str(tmp_path),
        )
    assert injected == dict.fromkeys(one_task_per_language(), 1)
    for task_id, sample in by_task(log).items():
        assert sample.error is None
        retries = sample.error_retries or []
        assert len(retries) == 1, task_id
        assert START_FAILURE in retries[0].message, (task_id, retries[0].message)
        assert scored(sample) == scored(uninjected[task_id]), task_id


@pytest.mark.docker
def test_a_container_killed_mid_attempt_is_retried_with_the_same_seed(
    uninjected: dict[str, EvalSample], tmp_path: Path
) -> None:
    model, kills = killing_model(AGENT, MASTER_SEED)
    log = run_eval(model, task_ids=one_task_per_language(), log_dir=str(tmp_path))
    assert kills == dict.fromkeys(one_task_per_language(), 1)
    for task_id, sample in by_task(log).items():
        assert sample.error is None
        retries = sample.error_retries or []
        assert len(retries) == 1, task_id
        # The retry came from the killed container, not from anything else.
        assert CONTAINER_GONE in retries[0].message, (task_id, retries[0].message)
        assert scored(sample) == scored(uninjected[task_id]), task_id


@pytest.mark.docker
def test_a_container_that_fails_every_time_is_excluded_and_never_scored(
    docker_engine: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken, fine = one_task_per_language()[:2]
    with failing_starts(monkeypatch, times=ALWAYS, task_ids={broken}) as injected:
        log = run_eval(
            honest_model(AGENT, master_seed=MASTER_SEED),
            task_ids=[broken, fine],
            log_dir=str(tmp_path),
            fail_on_error=2,  # an absolute cap: one excluded attempt does not stop the eval
        )
    assert injected[broken] == 3  # the try and its 2 retries (retry_on_error=2)
    assert log.status == "success"
    samples = {str(s.id): s for s in log.samples or []}
    assert samples[broken].error is not None
    assert len(samples[broken].error_retries or []) == 2
    assert not samples[broken].scores  # never scored, so never an agent failure
    assert samples[fine].error is None
    # The report excludes it from every statistic and counts it as an infrastructure failure.
    run = report.read_run(tmp_path.glob("*.eval"))
    assert run.excluded == 1
    stats = report.agent_stats(run.attempts, AGENT)
    assert set(stats.counts) == {fine}


# --- E4 across a retry ------------------------------------------------------------------------


def marker_then_killed_model(token: str) -> Model:
    """On its first try at a task: check, leave markers everywhere, check again, then kill its own
    container and submit, so the scorer meets the dead container. On the retry: check, then
    submit."""
    tries: dict[str, int] = {}
    first = [check(token), leave(token), check(token)]

    def policy(turn: Turn) -> ModelOutput:
        if turn.step == 0:
            tries[turn.task_id] = tries.get(turn.task_id, 0) + 1
        model = "mockllm/marker"
        if tries[turn.task_id] == 1 and turn.step < len(first):
            return tool_call(model, "bash", command=first[turn.step])
        if tries[turn.task_id] == 1:
            kill_own_agent_container()
            return submit(model)
        return tool_call(model, "bash", command=check(token)) if turn.step == 0 else submit(model)

    return scripted_model(policy, "marker")


@pytest.mark.docker
def test_a_retry_after_a_killed_container_starts_clean(docker_engine: None, tmp_path: Path) -> None:
    token = f"evalh-e6-{uuid.uuid4().hex}"
    # The real scorer: it is what meets the dead container and fails the first try.
    log = run_eval(
        marker_then_killed_model(token), task_ids=one_task_per_language(), log_dir=str(tmp_path)
    )
    for task_id, sample in by_task(log).items():
        retries = sample.error_retries or []
        assert len(retries) == 1, task_id
        assert CONTAINER_GONE in retries[0].message, (task_id, retries[0].message)
        [retry_check] = bash_outputs(sample)  # the final try's only bash call
        assert parse_check(retry_check) == {
            "holds-token": [],
            "marker": [],
            "commits": ["1"],
            "tree": [pristine_tree_hash(task_id)],
        }, (task_id, retry_check)
