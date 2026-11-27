"""The scripted agents as RL policies (D82), and the environment's checks that need no Docker.

A policy must play exactly the eval's script, turn by turn, and an honest policy must draw the
same outcome as the eval's attempt with the same seed, so an episode replays an attempt.
"""

from __future__ import annotations

from dataclasses import asdict
from functools import cache

import pytest
from inspect_ai.log import read_eval_log
from inspect_ai.model import ChatMessageAssistant, ModelOutput

from harness.agents import cheaters, honest
from harness.agents.outcomes import AGENTS, Outcome, attempt_seed
from harness.agents.rl_policy import (
    POLICIES,
    action_of,
    action_of_call,
    honest_outcome,
    scripted_outputs,
    scripted_policy,
)
from harness.agents.scripted import Turn, submit, tool_call
from rl.env import MAX_OUTPUT_BYTES, Action, Create, Env, Replace, Run, Submit, View, _truncate
from stats.report import LOG_DIR, SCORER

TASK = "risk-001"
MODEL = "mockllm/test"


A = "/work/repo/a.py"
B = "/work/repo/b.py"
EDITOR = "text_editor"


@pytest.mark.parametrize(
    ("output", "action"),
    [
        (tool_call(MODEL, "bash", command="ls"), Run("ls")),
        (tool_call(MODEL, EDITOR, command="view", path=A), View(A)),
        (tool_call(MODEL, EDITOR, command="create", path=B, file_text="x"), Create(B, "x")),
        (
            tool_call(MODEL, EDITOR, command="str_replace", path=A, old_str="a", new_str="b"),
            Replace(A, "a", "b"),
        ),
        (submit(MODEL), Submit("done")),
    ],
)
def test_each_tool_call_becomes_its_action(output: ModelOutput, action: object) -> None:
    assert action_of(output) == action


def test_a_tool_without_an_action_is_refused() -> None:
    with pytest.raises(ValueError, match="no action"):
        action_of(tool_call(MODEL, "python", code="print(1)"))
    with pytest.raises(ValueError, match="no action"):
        action_of(tool_call(MODEL, "text_editor", command="undo_edit", path="/work/repo/a.py"))


def test_an_honest_policy_draws_the_eval_attempts_outcome() -> None:
    """The eval's attempt with seed s and the episode with seed s draw the same outcome."""
    for name in AGENTS:
        for epoch in range(1, 7):
            turn = Turn(task_id=TASK, epoch=epoch, step=0, messages=[])
            info = honest.plan(name, honest.DEFAULT_MASTER_SEED, turn)
            assert info.seed is not None
            assert honest_outcome(name, TASK, info.seed).value == info.outcome, asdict(info)


@pytest.mark.parametrize("name", POLICIES)
def test_a_policy_plays_the_eval_script_turn_by_turn(name: str) -> None:
    seed = attempt_seed(honest.DEFAULT_MASTER_SEED, name, TASK, 1) if name in AGENTS else None
    if name in AGENTS:
        assert seed is not None
        outcome = honest_outcome(name, TASK, seed)
        expected = [honest.output_at(name, TASK, outcome, step) for step in range(40)]
    elif name == honest.ORACLE:
        expected = [honest.output_at(name, TASK, Outcome.SUCCESS, step) for step in range(40)]
    else:
        steps = cheaters.script(name, TASK)
        expected = [steps[min(step, len(steps) - 1)] for step in range(40)]
    policy = scripted_policy(name, TASK, seed)
    assert [policy("ignored") for _ in range(40)] == [action_of(o) for o in expected]


def test_the_same_seed_gives_the_same_actions_and_seeds_change_the_outcome() -> None:
    def actions(seed: int) -> list[object]:
        policy = scripted_policy("mid", TASK, seed)
        return [policy("") for _ in range(30)]

    assert actions(11) == actions(11)
    outcomes = {honest_outcome("mid", TASK, seed) for seed in range(200)}
    assert len(outcomes) > 1


def test_an_honest_policy_needs_a_seed_and_unknown_names_are_refused() -> None:
    with pytest.raises(ValueError, match="needs a seed"):
        scripted_outputs("strong", TASK, None)
    with pytest.raises(ValueError, match="unknown scripted policy"):
        scripted_outputs("nobody", TASK, 1)


def test_a_step_without_an_episode_is_refused() -> None:
    with Env() as env, pytest.raises(RuntimeError, match="call reset first"):
        env.step(Submit())


def test_long_output_is_cut_to_inspects_tool_output_limit() -> None:
    assert _truncate("short") == "short"
    cut = _truncate("é" * MAX_OUTPUT_BYTES)
    assert len(cut.split("\n")[0].encode()) <= MAX_OUTPUT_BYTES
    assert cut.endswith(f"[output truncated to {MAX_OUTPUT_BYTES} bytes]")


@cache
def logged_trajectories() -> list[tuple[str, str, int, int | None, list[Action]]]:
    """Every attempt of the committed full run (D19): agent, task, epoch, seed, and the tool calls
    it made, as actions."""
    found = []
    for path in sorted(LOG_DIR.glob("*.eval")):
        log = read_eval_log(str(path))
        agent = log.eval.model.removeprefix("mockllm/")
        for sample in log.samples or []:
            record = (sample.scores or {})[SCORER].metadata or {}
            seed = (record.get("agent") or {}).get("seed")
            calls = [
                action_of_call(call)
                for m in sample.messages
                if isinstance(m, ChatMessageAssistant)
                for call in m.tool_calls or []
            ]
            found.append((agent, str(sample.id), int(sample.epoch), seed, calls))
    return found


def test_every_logged_attempt_is_replayed_call_for_call() -> None:
    """D82: a policy with an attempt's seed plays exactly the tool calls that attempt made in the
    eval, for every attempt of the full run."""
    attempts = logged_trajectories()
    assert len(attempts) > 400
    for agent, task_id, epoch, seed, calls in attempts:
        policy = scripted_policy(agent, task_id, seed)
        assert [policy("") for _ in calls] == calls, (agent, task_id, epoch)
