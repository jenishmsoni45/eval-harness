"""What a scripted agent knows and draws (design.md 6, D5, D29).

- **True rate.** An agent's true rate on a task is `expit(logit(r_level) + SIGMA * z_task)`:
  `r_level` is its D5 rate for the task's difficulty level, and `z_task` is a standard normal
  offset drawn once per task from `OFFSET_SEED` and the task id, the same for every agent.
- **Attempt seed.** The first 8 bytes of SHA-256 over (master seed, agent, task id, epoch). A
  retry or a rerun of an attempt gets the same seed, so it makes the same choices.
- **Outcome.** Success with the true rate; otherwise one of the failure modes, with D29's mix.

Every draw uses Python's `random.Random`, whose `random()` sequence for a seed is fixed across
Python versions, and the normal offset uses the inverse normal CDF of one such draw, so the same
inputs give the same rates and outcomes everywhere.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from enum import StrEnum
from statistics import NormalDist

LEVELS = ("easy", "medium", "hard")
# D5: true success rates per difficulty level.
RATES: dict[str, dict[str, float]] = {
    "strong": {"easy": 0.9, "medium": 0.7, "hard": 0.5},
    "mid": {"easy": 0.75, "medium": 0.5, "hard": 0.3},
    "weak": {"easy": 0.5, "medium": 0.25, "hard": 0.1},
}
AGENTS = tuple(RATES)
# design.md 14: the per-task offset spread on the logit scale, and the seed of the offsets.
SIGMA = 0.7
OFFSET_SEED = 20261121


class Outcome(StrEnum):
    SUCCESS = "success"
    WRONG = "wrong"  # applies wrong.patch
    PARTIAL = "partial"  # applies partial.patch
    GIVE_UP = "give_up"  # looks at the code, changes nothing, submits
    OUT_OF_STEPS = "out_of_steps"  # keeps looking until the turn limit


# design.md 14: the failure mode of an attempt drawn to fail.
FAILURE_MIX: tuple[tuple[Outcome, float], ...] = (
    (Outcome.WRONG, 0.4),
    (Outcome.PARTIAL, 0.3),
    (Outcome.GIVE_UP, 0.2),
    (Outcome.OUT_OF_STEPS, 0.1),
)


def _seed(*parts: object) -> int:
    """The first 8 bytes of SHA-256 over the parts, each length-prefixed so that no two
    different part lists hash the same bytes."""
    digest = hashlib.sha256()
    for part in parts:
        data = str(part).encode()
        digest.update(len(data).to_bytes(8, "big") + data)
    return int.from_bytes(digest.digest()[:8], "big")


def _uniform_open(rng: random.Random) -> float:
    """A uniform draw strictly inside (0, 1), from 53 random bits."""
    return (rng.getrandbits(53) + 0.5) / 2**53


def task_offset(task_id: str) -> float:
    """z_task: the task's standard normal offset, shared by every agent."""
    rng = random.Random(_seed(OFFSET_SEED, task_id))  # noqa: S311 (a simulation, not a secret)
    return NormalDist().inv_cdf(_uniform_open(rng))


def expit(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def logit(p: float) -> float:
    return math.log(p / (1 - p))


def true_rate(agent: str, difficulty: str, task_id: str) -> float:
    return expit(logit(RATES[agent][difficulty]) + SIGMA * task_offset(task_id))


def attempt_seed(master_seed: int, agent: str, task_id: str, epoch: int) -> int:
    return _seed(master_seed, agent, task_id, epoch)


@dataclass(frozen=True)
class Draw:
    seed: int
    true_rate: float
    outcome: Outcome


def draw(seed: int, rate: float) -> Draw:
    """Success with probability `rate`; otherwise a failure mode from FAILURE_MIX."""
    rng = random.Random(seed)  # noqa: S311 (a simulation, not a secret)
    if rng.random() < rate:
        return Draw(seed, rate, Outcome.SUCCESS)
    u = rng.random()
    cumulative = 0.0
    for outcome, weight in FAILURE_MIX:
        cumulative += weight
        if u < cumulative:
            return Draw(seed, rate, outcome)
    return Draw(seed, rate, FAILURE_MIX[-1][0])  # u within rounding of 1
