"""The eval's scripted agents and cheaters as RL policies (D82).

A policy plays the same script as the agent does in the eval, turn by turn, and turns each tool
call into an environment action (rl/env.py): `bash` into `Run`, `text_editor` view, create and
str_replace into `View`, `Create` and `Replace`, and `submit` into `Submit`. The scripts never
read what the tools returned, so the policy ignores its observations.

An honest agent's seed is the attempt seed: it draws its outcome exactly as in the eval
(harness/agents/outcomes.py), so the same seed always gives the same trajectory, and that
trajectory is the one the eval runs for an attempt with this seed. The oracle and the cheaters
draw nothing.

This module lives in harness/agents/ so that rl/ never imports agent code (R4).
"""

from __future__ import annotations

from collections.abc import Callable

from inspect_ai.model import ModelOutput
from inspect_ai.tool import ToolCall

from harness.agents import cheaters, honest
from harness.agents.outcomes import AGENTS, Outcome, draw, true_rate
from harness.tasks import load_task
from rl.env import Action, Create, Policy, Replace, Run, Submit, View

POLICIES = (*AGENTS, honest.ORACLE, *cheaters.CHEATERS)


def action_of(output: ModelOutput) -> Action:
    """The environment action for a scripted output's one tool call."""
    calls = output.message.tool_calls or []
    if len(calls) != 1:
        raise ValueError(f"a scripted output makes exactly one tool call, not {len(calls)}")
    return action_of_call(calls[0])


def action_of_call(call: ToolCall) -> Action:
    """The environment action for one tool call, scripted or logged."""
    args = call.arguments
    if call.function == "bash":
        return Run(str(args["command"]))
    if call.function == "submit":
        return Submit(str(args.get("answer", "done")))
    if call.function == "text_editor":
        command = args["command"]
        if command == "view":
            return View(str(args["path"]))
        if command == "create":
            return Create(str(args["path"]), str(args["file_text"]))
        if command == "str_replace":
            return Replace(str(args["path"]), str(args["old_str"]), str(args["new_str"]))
        raise ValueError(f"text_editor command {command!r} has no action")
    raise ValueError(f"tool {call.function!r} has no action")


def honest_outcome(name: str, task_id: str, seed: int) -> Outcome:
    """The outcome an honest agent draws for an attempt with this seed (design.md 6)."""
    task = load_task(task_id)
    return draw(seed, true_rate(name, task.difficulty, task.id)).outcome


def scripted_outputs(name: str, task_id: str, seed: int | None) -> Callable[[int], ModelOutput]:
    """The scripted agent's output for each turn, counted from 0, as in the eval."""
    if name in AGENTS:
        if seed is None:
            raise ValueError(f"the honest agent {name!r} needs a seed")
        outcome = honest_outcome(name, task_id, seed)
        return lambda step: honest.output_at(name, task_id, outcome, step)
    if name == honest.ORACLE:
        return lambda step: honest.output_at(name, task_id, Outcome.SUCCESS, step)
    if name in cheaters.CHEATERS:
        steps = cheaters.script(name, task_id)
        return lambda step: steps[min(step, len(steps) - 1)]
    raise ValueError(f"unknown scripted policy {name!r}; expected one of {POLICIES}")


def scripted_policy(name: str, task_id: str, seed: int | None = None) -> Policy:
    """A policy for one episode of `name` on `task_id`."""
    outputs = scripted_outputs(name, task_id, seed)
    step = 0

    def policy(observation: str) -> Action:
        nonlocal step
        action = action_of(outputs(step))
        step += 1
        return action

    return policy
