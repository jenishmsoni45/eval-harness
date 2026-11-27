"""pass@k (design.md 7.2).

For a task with `n` attempts of which `c` succeeded, the unbiased estimator of the chance that at
least one of `k` attempts succeeds is `1 - C(n - c, k) / C(n, k)`: one minus the share of the
k-subsets of the attempts that hold no success. The bank's pass@k is its mean over tasks. pass@1
reduces to the mean of `c / n`.

A task with fewer than `k` attempts left (after excluded attempts are dropped) has no estimate at
that `k` and is left out of the mean at that `k` only (D78).
"""

from __future__ import annotations

from collections.abc import Iterable
from fractions import Fraction
from math import comb


def _check(n: int, c: int, k: int) -> None:
    if not 0 <= c <= n:
        raise ValueError(f"successes must be between 0 and the attempts: n={n}, c={c}")
    if not 1 <= k <= n:
        raise ValueError(f"k must be between 1 and the attempts: n={n}, k={k}")


def pass_at_k_exact(n: int, c: int, k: int) -> Fraction:
    """The estimator as an exact fraction."""
    _check(n, c, k)
    return 1 - Fraction(comb(n - c, k), comb(n, k))


def pass_at_k(n: int, c: int, k: int) -> float:
    """The estimator as a float (the exact fraction, rounded once)."""
    return float(pass_at_k_exact(n, c, k))


def mean_pass_at_k(tasks: Iterable[tuple[int, int]], k: int) -> float | None:
    """The mean over tasks, given each task's (attempts, successes); tasks with fewer than k
    attempts are left out. None when no task has k attempts."""
    values = [pass_at_k_exact(n, c, k) for n, c in tasks if n >= k]
    if not values:
        return None
    return float(sum(values, Fraction(0)) / len(values))
