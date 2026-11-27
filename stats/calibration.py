"""The rates a scripted agent's interval is checked against (design.md 7.1 and 7.5).

- **Bank rate:** the mean of the agent's true rate over the bank's tasks.
- **Population rate:** the expected true rate over tasks drawn the way the bank's were: the same
  difficulty mix and fresh per-task offsets, `E[expit(logit(r_level) + sigma * Z)]` for a
  standard normal Z, weighted by the mix, by Gauss-Hermite quadrature.

Both come from what the agents wrote into the logs (their true rate on each task, their rate for
each level and sigma), never from agent code (R4).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy.special import expit, logit

# Gauss-Hermite nodes for the population rate; far more than the integrand needs.
QUADRATURE_NODES = 101


def population_rate(rates: Sequence[float], mix: Sequence[int], sigma: float) -> float:
    """The mix-weighted mean over levels of E[expit(logit(rate) + sigma * Z)]."""
    if len(rates) != len(mix) or sum(mix) <= 0:
        raise ValueError("one rate per level and a mix with at least one task are needed")
    nodes, weights = np.polynomial.hermite_e.hermegauss(QUADRATURE_NODES)
    weights = weights / weights.sum()
    per_level = [float(np.dot(weights, expit(logit(r) + sigma * nodes))) for r in rates]
    return float(np.dot(per_level, mix) / sum(mix))


def bank_rate(true_rates: Sequence[float]) -> float:
    """The mean of the true rates, one per task."""
    if not true_rates:
        raise ValueError("no tasks")
    return float(np.mean(np.asarray(true_rates, dtype=np.float64)))
