"""Scripted adversaries for the adversarial tests (design.md 5 table, 13; phases.md P4-5).

Each test plays one script on `risk-001`, the fastest task: usually the reference fix, applied the
way the oracle applies it, plus one adversarial move. Each checks that the attempt is scored (never
an error to retry) and what its record says.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from inspect_ai.event import ToolEvent
from inspect_ai.log import EvalSample
from inspect_ai.model import Model, ModelOutput

from harness.agents.oracle import script
from harness.agents.scripted import Turn, scripted_model, submit, tool_call
from harness.eval import run_eval
from harness.testrun import REPO_DIR
from tests.runs import record, samples

TASK = "risk-001"
MODEL = "mockllm/adversary"
COMPUTE = f"{REPO_DIR}/risk/features/compute.py"


def bash(command: str) -> ModelOutput:
    return tool_call(MODEL, "bash", command=command)


def edit(path: str, old: str, new: str) -> ModelOutput:
    return tool_call(
        MODEL, "text_editor", command="str_replace", path=path, old_str=old, new_str=new
    )


def fix(task_id: str = TASK) -> list[ModelOutput]:
    """The oracle's edits of the reference fix, without its test runs and views."""
    edits = []
    for output in script(task_id):
        [call] = output.message.tool_calls or []
        if call.function == "text_editor" and call.arguments["command"] != "view":
            edits.append(output)
    assert edits
    return edits


def scripted(steps: list[ModelOutput]) -> Model:
    plan = [*steps, submit(MODEL)]

    def policy(turn: Turn) -> ModelOutput:
        return plan[min(turn.step, len(plan) - 1)].model_copy(deep=True)

    return scripted_model(policy, "adversary")


def attempt(
    steps: list[ModelOutput], tmp_path: Path, task_id: str = TASK, **limits: Any
) -> EvalSample:
    """Run the script once on a task; the attempt must be scored, not retried."""
    log = run_eval(scripted(steps), task_ids=task_id, log_dir=str(tmp_path), **limits)
    [sample] = samples(log)
    assert sample.error is None, sample.error
    assert not sample.error_retries
    return sample


def outputs(sample: EvalSample) -> list[str]:
    return [str(e.result) for e in sample.events if isinstance(e, ToolEvent)]


__all__ = ["COMPUTE", "TASK", "attempt", "bash", "edit", "fix", "outputs", "record"]
