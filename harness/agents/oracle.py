"""The oracle agent: always applies the task's reference fix (design.md 6).

It follows the same short script as every scripted agent, so its log reads like an agent's work:
run the visible tests, view each file the patch changes, write each change with text_editor, run
the visible tests again, submit.
"""

from __future__ import annotations

from functools import cache

from inspect_ai.model import Model, ModelOutput

from harness.agents.patches import Edit, parse_patch, plan_edits
from harness.agents.scripted import Turn, run_in_repo, scripted_model, submit, tool_call
from harness.tasks import load_task
from harness.testrun import REPO_DIR

NAME = "oracle"
MODEL = f"mockllm/{NAME}"


def _edit_call(edit: Edit) -> ModelOutput:
    path = f"{REPO_DIR}/{edit.path}"
    if edit.old is None:
        return tool_call(MODEL, "text_editor", command="create", path=path, file_text=edit.new)
    return tool_call(
        MODEL, "text_editor", command="str_replace", path=path, old_str=edit.old, new_str=edit.new
    )


@cache
def script(task_id: str) -> tuple[ModelOutput, ...]:
    task = load_task(task_id)
    patch = task.solution_patch.read_text()
    views = [
        tool_call(MODEL, "text_editor", command="view", path=f"{REPO_DIR}/{fp.path}")
        for fp in parse_patch(patch)
        if not fp.new_file
    ]
    edits = [_edit_call(edit) for edit in plan_edits(patch, task.repo_dir)]
    run_tests = run_in_repo(MODEL, task.visible_command)
    return (run_tests, *views, *edits, run_tests, submit(MODEL))


def policy(turn: Turn) -> ModelOutput:
    steps = script(turn.task_id)
    # A fresh copy each turn: Inspect records the output object it is given.
    return steps[min(turn.step, len(steps) - 1)].model_copy(deep=True)


def oracle_model() -> Model:
    return scripted_model(policy, NAME)
