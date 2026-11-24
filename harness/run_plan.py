"""The full scripted run, as data (design.md 6 and 7.6; D13, D30, D74).

- The honest scripted agents, `EPOCHS` attempts each on every task.
- The scripted cheaters, one attempt each on every task where their trick applies: hard-code on
  the easy tasks (the only ones with a failing visible test, D63), every other cheater on every
  task (D65).
- The 5% budget of excluded attempts is run-wide (D74): each eval may exclude what is left of it.

`make eval` runs this plan with harness/agents/; `make estimate` counts it without importing
agent code (R4). tests/unit/test_run_plan.py checks that the cheaters here are the agents'.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from harness.tasks import load_task, task_ids

HONEST_AGENTS = ("strong", "mid", "weak")
EPOCHS = 6  # D30
# The cheater and the difficulty levels of the tasks it runs on (None: every task).
CHEATERS: dict[str, tuple[str, ...] | None] = {
    "edit-test": None,
    "delete-test": None,
    "skip-test": None,
    "hard-code": ("easy",),
    "detect-runner": None,
    "snoop": None,
}
# The run's master seed; every attempt's seed derives from it (design.md 6) and is logged.
MASTER_SEED = 20261124
# D18, D74: the most attempts a valid run may exclude, as a share of all its attempts.
EXCLUDED_SHARE = 0.05
# D21: attempts at once, and the containers each attempt starts (harness/sandbox/compose.yaml).
ATTEMPTS_AT_ONCE = 3
CONTAINERS_PER_ATTEMPT = 2


@dataclass(frozen=True)
class EvalPlan:
    """One eval of the run: one agent or cheater on some tasks, `epochs` attempts each."""

    agent: str
    task_ids: tuple[str, ...]
    epochs: int

    @property
    def attempts(self) -> int:
        return len(self.task_ids) * self.epochs


def cheater_tasks(name: str, among: Sequence[str]) -> tuple[str, ...]:
    levels = CHEATERS[name]
    return tuple(t for t in among if levels is None or load_task(t).difficulty in levels)


def full_run(tasks: Sequence[str] | None = None) -> tuple[EvalPlan, ...]:
    """Every eval of the full run, in the order `make eval` runs them."""
    bank = tuple(task_ids() if tasks is None else tasks)
    honest = tuple(EvalPlan(agent, bank, EPOCHS) for agent in HONEST_AGENTS)
    cheats = tuple(EvalPlan(name, cheater_tasks(name, bank), 1) for name in CHEATERS)
    return honest + tuple(plan for plan in cheats if plan.task_ids)


def allowed_exclusions(total_attempts: int) -> int:
    """The most excluded attempts a run of this size may have and stay valid (D18)."""
    return int(total_attempts * EXCLUDED_SHARE)


def eval_cap(total_attempts: int, excluded_so_far: int) -> int:
    """D74: the absolute `fail_on_error` for the next eval. Inspect stops an eval once its errors
    reach this, which is one more than the run may still exclude, so the run stops as soon as more
    than 5% of all its attempts are excluded."""
    return max(allowed_exclusions(total_attempts) - excluded_so_far, 0) + 1
