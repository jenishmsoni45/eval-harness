"""The cluster bootstrap over tasks (design.md 7.3 and 7.4, D7).

Tasks are drawn with replacement, as many as there are; each drawn task brings its own value (its
success fraction, or a paired difference of two agents' fractions on it), and the statistic is
the mean of the drawn values. The interval is the central percentile interval of the replicates,
by numpy's default (linear) percentile method.

The indices are drawn separately from the replicates so that callers share them: the report draws
them once per set of tasks from a fixed seed, so every agent and pair over the same tasks is
resampled the same way, and `scripts/power_estimate.py` draws them from each simulated run's own
stream.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

CONFIDENCE = 0.95
# design.md 14: resamples in reports.
RESAMPLES = 10_000


def resample_indices(rng: np.random.Generator, n_tasks: int, resamples: int) -> NDArray[np.int64]:
    """`resamples` rows of `n_tasks` task indices, each drawn uniformly with replacement."""
    if n_tasks < 1:
        raise ValueError("the bootstrap needs at least one task")
    return rng.integers(0, n_tasks, size=(resamples, n_tasks))


def percentile_interval(samples: ArrayLike, confidence: float = CONFIDENCE) -> tuple[float, float]:
    """The central `confidence` interval of bootstrap replicates."""
    tail = (1 - confidence) / 2 * 100
    low, high = np.percentile(np.asarray(samples, dtype=np.float64), [tail, 100 - tail])
    return float(low), float(high)


def replicates(values: ArrayLike, indices: NDArray[np.int64]) -> NDArray[np.float64]:
    """The mean of the drawn tasks' values, one per resample."""
    per_task = np.asarray(values, dtype=np.float64)
    if indices.shape[1] != per_task.size:
        raise ValueError(f"{indices.shape[1]} indices per resample for {per_task.size} tasks")
    means: NDArray[np.float64] = per_task[indices].mean(axis=1)
    return means


def interval_from_indices(
    values: ArrayLike, indices: NDArray[np.int64], confidence: float = CONFIDENCE
) -> tuple[float, float]:
    return percentile_interval(replicates(values, indices), confidence)


def cluster_interval(
    values: ArrayLike, seed: int, resamples: int = RESAMPLES, confidence: float = CONFIDENCE
) -> tuple[float, float]:
    """The percentile interval of the mean of per-task values, from a fixed seed: the same
    values, seed and resamples always give the same interval."""
    per_task = np.asarray(values, dtype=np.float64)
    indices = resample_indices(np.random.default_rng(seed), per_task.size, resamples)
    return interval_from_indices(per_task, indices, confidence)
