"""The Inspect task (architecture.md, design.md 2).

One sample per task, each attempt in its own two-service compose project. The model is a
parameter (R4): scripted agents are `mockllm` models built in harness/agents/, which this module
never imports, and a real model could be passed instead.

    inspect eval harness/eval.py --model mockllm/model -T task_ids=risk-001
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from typing import Any

from inspect_ai import Task, task
from inspect_ai import eval as inspect_eval
from inspect_ai.agent import react
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import GenerateConfig, Model
from inspect_ai.tool import bash, text_editor
from inspect_ai.util import SandboxEnvironmentSpec

from harness.images import build_task_image
from harness.sample_identity import record_sample_identity
from harness.scorer import hidden_tests
from harness.tasks import REPO_ROOT, load_task, task_ids
from harness.testrun import REPO_DIR

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


@task(name=TASK_NAME)
def evalh(task_ids: str | Sequence[str] | None = None, epochs: int = 1) -> Task:
    """Every task in the bank, or the comma-separated `task_ids`, `epochs` attempts each.

    Builds any task image that is missing (content-hashed, so an unchanged task is not rebuilt).
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
        # attempts=1: with more, react() would score mid-attempt and tell the agent the result.
        solver=react(tools=[bash(), text_editor()], attempts=1),
        scorer=hidden_tests(),
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
) -> EvalLog:
    """Run the eval with the harness's concurrency and retry settings; return its log."""
    logs = inspect_eval(
        evalh(task_ids=task_ids, epochs=epochs),
        model=model,
        log_dir=log_dir,
        display="none",
        **EVAL_OPTIONS,
    )
    return logs[0]
