"""The honest scripted agents: strong, mid and weak (D5, design.md 6), and the oracle.

On its first turn an agent draws its outcome from its attempt seed and its true rate on the task
(harness/agents/outcomes.py) and writes them to the sample's store, from where the scorer copies
them into the attempt's record. Every turn then plays the same short script, so the log reads
like an agent's work:

1. run the visible tests;
2. view each file the patch changes;
3. write each change with text_editor;
4. run the visible tests again;
5. submit.

A success applies solution.patch, a wrong or partial outcome applies wrong.patch or
partial.patch. Giving up stops after step 2 and submits without a change; running out of steps
keeps viewing files until the turn limit ends the attempt. The patches are read on the host,
never inside the sandbox (D14). The oracle always succeeds and writes no true rate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import cache

from inspect_ai.model import Model, ModelOutput
from inspect_ai.util import store

from harness.agents.outcomes import AGENTS, Outcome, attempt_seed, draw, true_rate
from harness.agents.patches import Edit, parse_patch, plan_edits
from harness.agents.scripted import Turn, run_in_repo, scripted_model, submit, tool_call
from harness.attempt import AGENT_INFO_KEY
from harness.tasks import Task, load_task
from harness.testrun import REPO_DIR

# The master seed when a run gives none; a run records the one it used in every attempt.
DEFAULT_MASTER_SEED = 20261121
# The patch an outcome applies; giving up and running out of steps view solution.patch's files.
PATCH_OF = {
    Outcome.SUCCESS: "solution.patch",
    Outcome.WRONG: "wrong.patch",
    Outcome.PARTIAL: "partial.patch",
}
GIVE_UP_ANSWER = "I could not find the cause of the bug."


def model_id(name: str) -> str:
    return f"mockllm/{name}"


def _edit_call(model: str, edit: Edit) -> ModelOutput:
    path = f"{REPO_DIR}/{edit.path}"
    if edit.old is None:
        return tool_call(model, "text_editor", command="create", path=path, file_text=edit.new)
    return tool_call(
        model, "text_editor", command="str_replace", path=path, old_str=edit.old, new_str=edit.new
    )


def _views(model: str, patch: str) -> list[ModelOutput]:
    return [
        tool_call(model, "text_editor", command="view", path=f"{REPO_DIR}/{fp.path}")
        for fp in parse_patch(patch)
        if not fp.new_file
    ]


def _patch(task: Task, outcome: Outcome) -> str:
    return task.patches[PATCH_OF.get(outcome, "solution.patch")].read_text()


@cache
def script(name: str, task_id: str, outcome: Outcome) -> tuple[ModelOutput, ...]:
    """The outputs of an attempt with this outcome, turn by turn. Running out of steps has no
    end: its script is the steps before the loop, then `looped_views` repeats."""
    model = model_id(name)
    task = load_task(task_id)
    patch = _patch(task, outcome)
    run_tests = run_in_repo(model, task.visible_command)
    views = _views(model, patch)
    if outcome is Outcome.GIVE_UP:
        return (run_tests, *views, submit(model, GIVE_UP_ANSWER))
    if outcome is Outcome.OUT_OF_STEPS:
        return (run_tests,)
    edits = [_edit_call(model, edit) for edit in plan_edits(patch, task.repo_dir)]
    return (run_tests, *views, *edits, run_tests, submit(model))


def output_at(name: str, task_id: str, outcome: Outcome, step: int) -> ModelOutput:
    """The output for turn `step` (counted from 0), a fresh copy each time: Inspect records the
    object it is given."""
    steps = script(name, task_id, outcome)
    if outcome is Outcome.OUT_OF_STEPS and step >= len(steps):
        views = _views(model_id(name), _patch(load_task(task_id), outcome))
        return views[(step - len(steps)) % len(views)].model_copy(deep=True)
    return steps[min(step, len(steps) - 1)].model_copy(deep=True)


@dataclass(frozen=True)
class AgentInfo:
    """What a scripted agent writes about its attempt; the scorer logs it (design.md 6)."""

    name: str
    master_seed: int | None
    seed: int | None
    true_rate: float | None
    outcome: str


def plan(name: str, master_seed: int, turn: Turn, forced: Outcome | None = None) -> AgentInfo:
    """The attempt's seed, true rate and outcome. `forced` replaces the drawn outcome; tests use
    it to run one failure mode on purpose."""
    task = load_task(turn.task_id)
    seed = attempt_seed(master_seed, name, turn.task_id, turn.epoch)
    drawn = draw(seed, true_rate(name, task.difficulty, task.id))
    outcome = forced if forced is not None else drawn.outcome
    return AgentInfo(name, master_seed, seed, drawn.true_rate, outcome.value)


def honest_model(
    name: str, master_seed: int = DEFAULT_MASTER_SEED, outcome: Outcome | None = None
) -> Model:
    """The `mockllm/<name>` scripted agent, for name in strong, mid and weak."""
    if name not in AGENTS:
        raise ValueError(f"unknown scripted agent {name!r}; expected one of {AGENTS}")

    def policy(turn: Turn) -> ModelOutput:
        info = plan(name, master_seed, turn, outcome)
        if turn.step == 0:
            store().set(AGENT_INFO_KEY, asdict(info))
        return output_at(name, turn.task_id, Outcome(info.outcome), turn.step)

    return scripted_model(policy, name)


ORACLE = "oracle"


def oracle_model() -> Model:
    """Always applies the reference fix; used for E5 and to check every task scores base 1."""

    def policy(turn: Turn) -> ModelOutput:
        if turn.step == 0:
            info = AgentInfo(ORACLE, None, None, None, Outcome.SUCCESS.value)
            store().set(AGENT_INFO_KEY, asdict(info))
        return output_at(ORACLE, turn.task_id, Outcome.SUCCESS, turn.step)

    return scripted_model(policy, ORACLE)
