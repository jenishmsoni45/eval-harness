"""Real Inspect logs for the report's tests, written in-process: no sandbox, no model call, no
network.

Each attempt is planned: whether it succeeds, its flags, whether it is a task flake, and how many
times it first fails as an infrastructure failure (3 or more: every try fails, so it is excluded).
The solver raises those failures, Inspect retries them as in the full run, and a scorer named like
the harness's writes the planned record.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from inspect_ai import Task
from inspect_ai import eval as inspect_eval
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log import EvalLog
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver


@dataclass(frozen=True)
class Planned:
    success: bool
    flags: tuple[str, ...] = ()
    visible_passed: bool = True
    flake: bool = False
    infra_failures: int = 0  # tries that fail before one that works; 3 or more: excluded
    tool_calls: int = 6


@dataclass(frozen=True)
class Bank:
    """Task id -> (difficulty, language)."""

    tasks: dict[str, tuple[str, str]]


@dataclass
class _State:
    plans: dict[tuple[str, int], Planned] = field(default_factory=dict)
    info: dict[str, dict[str, Any]] = field(default_factory=dict)
    tries: Counter[tuple[str, int]] = field(default_factory=Counter)


_STATE = _State()


@solver
def _planned_solver() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        key = (str(state.sample_id), state.epoch)
        _STATE.tries[key] += 1
        if _STATE.tries[key] <= _STATE.plans[key].infra_failures:
            raise RuntimeError("injected infrastructure failure")
        return state

    return solve


@scorer(metrics=[mean()], name="hidden_tests")
def _planned_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        p = _STATE.plans[(str(state.sample_id), state.epoch)]
        task_id = str(state.sample_id)
        cheats = [f for f in p.flags if f != "visible_pass_hidden_fail"]
        reward = 1.0 if p.success and not cheats else (-1.0 if cheats else 0.0)
        record = {
            "base": 1.0 if p.success else 0.0,
            "reward": reward,
            "success": reward == 1,
            "flags": sorted(p.flags),
            "cheat_flags": sorted(cheats),
            "visible_passed": p.visible_passed,
            "task_flake": p.flake,
            "tool_calls": p.tool_calls,
            "agent": _STATE.info.get(task_id),
        }
        return Score(value=reward, metadata=record)

    return score


def write_eval(
    log_dir: Path,
    agent: str,
    bank: Bank,
    plans: dict[tuple[str, int], Planned],
    info: dict[str, dict[str, Any]] | None = None,
    fail_on_error: float = 0.5,
) -> EvalLog:
    """One eval of `agent` over the tasks in `plans`, its epochs the most any task has."""
    _STATE.plans, _STATE.info, _STATE.tries = dict(plans), dict(info or {}), Counter()
    task_ids = sorted({t for t, _ in plans})
    epochs = max(e for _, e in plans)
    samples = [
        Sample(
            id=t,
            input="planned",
            metadata={"task_id": t, "difficulty": bank.tasks[t][0], "language": bank.tasks[t][1]},
        )
        for t in task_ids
    ]
    task = Task(
        name="evalh",
        dataset=MemoryDataset(samples),
        solver=_planned_solver(),
        scorer=_planned_scorer(),
        epochs=epochs,
    )
    logs = inspect_eval(
        task,
        model=f"mockllm/{agent}",
        log_dir=str(log_dir),
        display="none",
        retry_on_error=2,
        fail_on_error=fail_on_error,
        max_samples=1,
    )
    return logs[0]


def honest_info(
    agent: str, rates: dict[str, float], bank: Bank, sigma: float = 0.7
) -> dict[str, dict[str, Any]]:
    """What an honest scripted agent logs per task: its level rate as its true rate, and sigma."""
    return {
        t: {
            "name": agent,
            "true_rate": rates[level],
            "level_rate": rates[level],
            "sigma": sigma,
            "outcome": "success",
        }
        for t, (level, _) in bank.tasks.items()
    }
