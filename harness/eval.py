"""The Inspect task (architecture.md, design.md 2).

One sample per task, each attempt in its own two-service compose project. The model is a
parameter (R4): scripted agents are `mockllm` models built in harness/agents/, which this module
never imports, and a real model could be passed instead.

    inspect eval harness/eval.py --model mockllm/model -T task_ids=risk-001
"""

from __future__ import annotations

import shlex
import time
from collections.abc import Sequence
from typing import Any

from inspect_ai import Task, task
from inspect_ai import eval as inspect_eval
from inspect_ai.agent import AgentSubmit, as_solver, react
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import GenerateConfig, Model
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import bash, text_editor
from inspect_ai.util import LimitExceededError, SandboxEnvironmentSpec, time_limit, turn_limit

from harness.attempt import (
    AGENT_SECONDS_KEY,
    AGENT_TIME_LIMIT_S,
    LIMIT_HIT_KEY,
    MAX_TURNS,
    SCORING_TIME_LIMIT_S,
)
from harness.images import build_task_image
from harness.sample_identity import record_sample_identity
from harness.scorer import hidden_tests
from harness.tasks import REPO_ROOT, load_task, task_ids
from harness.testrun import AGENT_USER, REPO_DIR

# Inspect names each sample's compose project inspect-<first 12 characters of the task name>-i
# <random>, so this name gives inspect-evalh-i<random> (D25).
TASK_NAME = "evalh"
COMPOSE_TEMPLATE = REPO_ROOT / "harness" / "sandbox" / "compose.yaml"

# D21: three attempts at once. D18: up to 2 retries per attempt, and a run with more than 5% of
# attempts failing is stopped. Passed to inspect_ai.eval() by run_eval().
EVAL_OPTIONS: dict[str, Any] = {"max_samples": 3, "retry_on_error": 2, "fail_on_error": 0.05}

# task-spec.md "instructions.md": the same preamble for every task, before its instructions.
PREAMBLE = """\
You are fixing a bug in the repository at {repo}.
Run the visible tests with: {command}
Do not change tests, test configuration or build configuration.
There is no network access.
When you are finished, call submit.
"""


def _prompt(command: Sequence[str], instructions: str) -> str:
    preamble = PREAMBLE.format(repo=REPO_DIR, command=f"cd {REPO_DIR} && {shlex.join(command)}")
    return f"{preamble}\n{instructions}"


def _parse_ids(ids: str | Sequence[str] | None) -> list[str]:
    if ids is None:
        return task_ids()
    if isinstance(ids, str):
        return [i.strip() for i in ids.split(",") if i.strip()]
    return list(ids)


@solver
def limited_agent(max_turns: int = MAX_TURNS, time_limit_s: float = AGENT_TIME_LIMIT_S) -> Solver:
    """The agent under test (design.md 2): react() with bash and text_editor and one submission,
    ended by the turn or the time limit (D21).

    The limits are opened here, around the agent, rather than as the task's limits: Inspect gives
    the scorers half of a task's time limit and counts running past it as an error to retry,
    while a slow scoring run is the agent's outcome (design.md 3, D51). Inspect still records the
    limit in the sample; it is also noted in the store, with the agent's wall time, for the
    attempt's record.
    """
    # attempts=1: with more, react() would score mid-attempt and tell the agent the result.
    # keep_in_messages: react() would otherwise drop the submit call from the conversation, and
    # the record counts tool calls from it. Both tools run as `agent`, never as the containers'
    # root init (D60).
    agent = react(
        tools=[bash(user=AGENT_USER), text_editor(user=AGENT_USER)],
        attempts=1,
        submit=AgentSubmit(keep_in_messages=True),
    )

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # A limit counts from when it is opened and can be opened only once, so each attempt
        # gets its own.
        limited = as_solver(agent, limits=[turn_limit(max_turns), time_limit(time_limit_s)])
        start = time.monotonic()
        try:
            return await limited(state, generate)
        except LimitExceededError as error:
            state.store.set(LIMIT_HIT_KEY, error.type)
            raise  # Inspect ends the agent phase and goes on to scoring
        finally:
            state.store.set(AGENT_SECONDS_KEY, round(time.monotonic() - start, 3))

    return solve


@task(name=TASK_NAME)
def evalh(
    task_ids: str | Sequence[str] | None = None,
    epochs: int = 1,
    max_turns: int = MAX_TURNS,
    time_limit_s: float = AGENT_TIME_LIMIT_S,
    scoring_limit_s: float = SCORING_TIME_LIMIT_S,
) -> Task:
    """Every task in the bank, or the comma-separated `task_ids`, `epochs` attempts each.

    The limits default to D21's; tests shorten the time limits (D52). Builds any task image that
    is missing (content-hashed, so an unchanged task is not rebuilt).
    """
    samples = []
    for task_id in _parse_ids(task_ids):
        t = load_task(task_id)
        samples.append(
            Sample(
                id=t.id,
                input=_prompt(t.visible_command, t.instructions),
                # `image` fills ${SAMPLE_METADATA_IMAGE} in the compose template.
                metadata={"task_id": t.id, "image": build_task_image(t)},
                sandbox=SandboxEnvironmentSpec("docker", str(COMPOSE_TEMPLATE)),
            )
        )
    return Task(
        name=TASK_NAME,
        dataset=MemoryDataset(samples),
        setup=record_sample_identity(),
        solver=limited_agent(max_turns, time_limit_s),
        scorer=hidden_tests(scoring_limit_s),
        # One tool call per turn (D27).
        config=GenerateConfig(parallel_tool_calls=False),
        epochs=epochs,
        fail_on_error=EVAL_OPTIONS["fail_on_error"],
    )


def run_eval(
    model: str | Model,
    task_ids: str | Sequence[str] | None = None,
    epochs: int = 1,
    log_dir: str | None = None,
    *,
    task: Task | None = None,
    max_samples: int = EVAL_OPTIONS["max_samples"],
    **limits: Any,
) -> EvalLog:
    """Run the eval with the harness's concurrency and retry settings; return its log.

    `limits` are passed to `evalh` (max_turns, time_limit_s, scoring_limit_s). A test may pass
    its own `task` built from `evalh`, and fewer samples at once.
    """
    options = {**EVAL_OPTIONS, "max_samples": max_samples}
    logs = inspect_eval(
        task if task is not None else evalh(task_ids=task_ids, epochs=epochs, **limits),
        model=model,
        log_dir=log_dir,
        display="none",
        **options,
    )
    return logs[0]
