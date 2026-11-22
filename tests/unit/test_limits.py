"""The turn, time and scoring limits (D21, design.md 2 and 3, phases.md P3-4, D51, D52).

Each limit ends an attempt, the attempt is still scored (reaching a limit is the agent's outcome,
never an error to retry), and the attempt's record names the limit hit. The turn limit runs at
its real value; the time and scoring limits run at a few seconds against an agent and a change
that overrun them (D52), and a static test checks the eval's defaults are D21's.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from inspect_ai.model import Model, ModelOutput

from harness import eval as harness_eval
from harness.agents.outcomes import Outcome
from harness.agents.scripted import Turn, scripted_model, submit, tool_call
from harness.attempt import AGENT_TIME_LIMIT_S, MAX_TURNS, SCORING_TIME_LIMIT_S
from harness.scorer import hidden_tests, score_attempt
from harness.testrun import REPO_DIR
from scripts import validate_tasks
from tests.runs import base, by_task, record, samples

if TYPE_CHECKING:
    from inspect_ai.log import EvalLog, EvalSample

PROBE = "mockllm/limits"
PYTHON_TASK = "risk-001"


def test_the_defaults_are_d21s() -> None:
    assert (MAX_TURNS, AGENT_TIME_LIMIT_S, SCORING_TIME_LIMIT_S) == (30, 600, 300)
    params = inspect.signature(harness_eval.evalh).parameters
    assert params["max_turns"].default == MAX_TURNS
    assert params["time_limit_s"].default == AGENT_TIME_LIMIT_S
    assert params["scoring_limit_s"].default == SCORING_TIME_LIMIT_S
    agent = inspect.signature(harness_eval.limited_agent).parameters
    assert (agent["max_turns"].default, agent["time_limit_s"].default) == (30, 600)
    assert inspect.signature(hidden_tests).parameters["scoring_limit_s"].default == 300
    assert inspect.signature(score_attempt).parameters["scoring_limit_s"].default == 300
    # The validator's V13 bound is half of the same scoring limit.
    assert validate_tasks.SCORING_LIMIT_S == SCORING_TIME_LIMIT_S
    assert harness_eval.EVAL_OPTIONS["max_samples"] == 3


def scripted(steps: list[ModelOutput]) -> Model:
    def policy(turn: Turn) -> ModelOutput:
        return steps[min(turn.step, len(steps) - 1)].model_copy(deep=True)

    return scripted_model(policy, "limits")


def assert_scored_not_retried(sample: EvalSample) -> None:
    assert sample.error is None
    assert not sample.error_retries
    assert sample.scores


@pytest.mark.docker
def test_the_turn_limit_ends_an_attempt_at_30_tool_calls(
    failure_mode_runs: dict[str, EvalLog],
) -> None:
    """An agent that never submits (running out of steps) makes 30 tool calls; the 31st turn is
    stopped before its call runs."""
    [sample] = samples(failure_mode_runs[Outcome.OUT_OF_STEPS])
    assert_scored_not_retried(sample)
    assert sample.limit is not None
    assert (sample.limit.type, sample.limit.limit) == ("turn", MAX_TURNS)
    assert record(sample)["limits_hit"] == ["turn"]
    assert record(sample)["tool_calls"] == MAX_TURNS
    assert base(sample) == 0


@pytest.mark.docker
def test_the_time_limit_ends_an_attempt(docker_engine: None, tmp_path: Path) -> None:
    limit_s = 5
    model = scripted([tool_call(PROBE, "bash", command="sleep 120"), submit(PROBE)])
    log = harness_eval.run_eval(
        model, task_ids=PYTHON_TASK, log_dir=str(tmp_path), time_limit_s=limit_s
    )
    [sample] = samples(log)
    assert_scored_not_retried(sample)
    assert sample.limit is not None
    assert sample.limit.type == "time"
    assert record(sample)["limits_hit"] == ["time"]
    assert limit_s <= record(sample)["agent_seconds"] < limit_s + 10
    assert record(sample)["tool_calls"] == 1  # the sleep, cut short; submit never came
    assert base(sample) == 0


# Prepended to the module the risk-001 bug tests import: every hidden test hangs.
HANG = "import time\n\ntime.sleep(3600)\n"


@pytest.mark.docker
def test_the_scoring_limit_ends_scoring_and_counts_unfinished_tests_as_failed(
    docker_engine: None, tmp_path: Path
) -> None:
    """Code that hangs under the hidden tests: the first bug test is stopped at the scoring
    limit, it and every later test count as failed, and this is the agent's outcome, not an
    infrastructure failure to retry."""
    limit_s = 10
    path = f"{REPO_DIR}/risk/features/compute.py"
    first_import = "from __future__ import annotations\n"
    model = scripted(
        [
            tool_call(
                PROBE,
                "text_editor",
                command="str_replace",
                path=path,
                old_str=first_import,
                new_str=f"{first_import}\n{HANG}",
            ),
            submit(PROBE),
        ]
    )
    log = harness_eval.run_eval(
        model, task_ids=PYTHON_TASK, log_dir=str(tmp_path), scoring_limit_s=limit_s
    )
    sample = by_task(log)[PYTHON_TASK]
    assert_scored_not_retried(sample)
    assert sample.limit is None  # no agent limit was hit
    meta = record(sample)
    assert meta["limits_hit"] == ["scoring"]
    assert meta["scoring_limit_hit"] is True
    assert not any(meta["bug_tests"].values())
    assert meta["regression_passed"] is False
    assert base(sample) == 0
    # Stopped at the limit: the in-container timeout's 5-second grace and the scorer's own
    # reading and writing come on top.
    assert limit_s <= meta["scoring_seconds"] < limit_s + 20
    assert meta["changed_files"] == ["risk/features/compute.py"]


@pytest.mark.docker
def test_no_limit_is_recorded_when_none_is_hit(failure_mode_runs: dict[str, EvalLog]) -> None:
    for sample in samples(failure_mode_runs[Outcome.GIVE_UP]):
        assert sample.limit is None
        assert record(sample)["limits_hit"] == []
        assert record(sample)["scoring_limit_hit"] is False
