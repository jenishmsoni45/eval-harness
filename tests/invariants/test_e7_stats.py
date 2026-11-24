"""E7 (design.md 1, 7.2, 7.3, 7.6; phases.md P5-1): pass@k equals brute-force enumeration exactly
for every case with n <= 8; the bootstrap's coverage of the population rate is within
[0.93, 0.99] at the D30 run size; the same seed gives identical intervals.

The coverage simulation is scripts/power_estimate.py's, which resamples with stats/bootstrap.py,
the report's own interval code.
"""

from __future__ import annotations

import itertools
from fractions import Fraction
from math import comb

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from scripts import power_estimate as pe
from stats import bootstrap
from stats.calibration import bank_rate, population_rate
from stats.passk import mean_pass_at_k, pass_at_k, pass_at_k_exact

# --- pass@k against brute force -----------------------------------------------------------------


def brute_force_pass_at_k(outcomes: tuple[bool, ...], k: int) -> Fraction:
    """The share of the k-subsets of the attempts that hold at least one success."""
    subsets = list(itertools.combinations(outcomes, k))
    return Fraction(sum(any(s) for s in subsets), len(subsets))


def test_pass_at_k_equals_enumeration_for_every_case_up_to_8_attempts() -> None:
    checked = 0
    for n in range(1, 9):
        for outcomes in itertools.product((False, True), repeat=n):
            c = sum(outcomes)
            for k in range(1, n + 1):
                expected = brute_force_pass_at_k(outcomes, k)
                assert pass_at_k_exact(n, c, k) == expected, (outcomes, k)
                assert pass_at_k(n, c, k) == float(expected), (outcomes, k)
                checked += 1
    assert checked == sum(2**n * n for n in range(1, 9))


def test_the_bank_mean_equals_enumeration_over_every_small_bank() -> None:
    # Every bank of two tasks with up to 4 attempts each: the mean over tasks of the brute-force
    # share, with tasks that have fewer than k attempts left out.
    banks = [
        ((n1, c1), (n2, c2))
        for n1, n2 in itertools.product(range(1, 5), repeat=2)
        for c1 in range(n1 + 1)
        for c2 in range(n2 + 1)
    ]
    for bank in banks:
        for k in range(1, 5):
            shares = [
                brute_force_pass_at_k((True,) * c + (False,) * (n - c), k)
                for n, c in bank
                if n >= k
            ]
            expected = float(sum(shares, Fraction(0)) / len(shares)) if shares else None
            assert mean_pass_at_k(bank, k) == expected, (bank, k)


def test_pass_at_k_is_unbiased_for_the_chance_that_one_of_k_attempts_succeeds() -> None:
    # E[pass@k] over the binomial number of successes is exactly 1 - (1 - p)^k.
    for p in (Fraction(1, 10), Fraction(1, 2), Fraction(7, 10), Fraction(19, 20)):
        for n in range(1, 9):
            for k in range(1, n + 1):
                expectation = sum(
                    comb(n, c) * p**c * (1 - p) ** (n - c) * pass_at_k_exact(n, c, k)
                    for c in range(n + 1)
                )
                assert expectation == 1 - (1 - p) ** k, (p, n, k)


@given(st.integers(1, 30).flatmap(lambda n: st.tuples(st.just(n), st.integers(0, n))))
def test_pass_at_k_properties(nc: tuple[int, int]) -> None:
    n, c = nc
    values = [pass_at_k_exact(n, c, k) for k in range(1, n + 1)]
    assert all(0 <= v <= 1 for v in values)
    assert values == sorted(values)  # more attempts never lower the chance
    assert values[0] == Fraction(c, n)  # pass@1 is the success fraction
    assert values[-1] == (1 if c else 0)  # all n attempts succeed somewhere iff any did
    # k attempts must include a success exactly when k is more than the failures.
    for k, value in enumerate(values, start=1):
        assert (value == 1) == (c > 0 and k > n - c), (k, value)


@given(st.lists(st.integers(1, 8).flatmap(lambda n: st.tuples(st.just(n), st.integers(0, n))),
                min_size=1, max_size=12))  # fmt: skip
def test_pass_at_1_is_the_mean_success_fraction(bank: list[tuple[int, int]]) -> None:
    assert mean_pass_at_k(bank, 1) == pytest.approx(
        float(sum((Fraction(c, n) for n, c in bank), Fraction(0)) / len(bank)), abs=1e-15
    )


def test_tasks_with_too_few_attempts_are_left_out_at_that_k() -> None:
    bank = [(6, 3), (2, 1)]
    assert mean_pass_at_k(bank, 3) == float(pass_at_k_exact(6, 3, 3))
    assert mean_pass_at_k([(2, 1)], 3) is None


@pytest.mark.parametrize(("n", "c", "k"), [(0, 0, 1), (3, 4, 1), (3, -1, 1), (3, 1, 0), (3, 1, 4)])
def test_impossible_counts_are_refused(n: int, c: int, k: int) -> None:
    with pytest.raises(ValueError, match="must be between"):
        pass_at_k_exact(n, c, k)


# --- The bootstrap ------------------------------------------------------------------------------


def test_the_coverage_of_the_population_rate_is_within_the_band_at_the_run_size() -> None:
    """design.md 7.6: S = 2,000 synthetic runs of 20 tasks (7 easy, 7 medium, 6 hard) x 6
    attempts, B = 2,000 resamples each."""
    settings = pe.Settings()
    assert (settings.runs, settings.resamples, settings.mix, settings.attempts) == (
        2000,
        2000,
        (7, 7, 6),
        6,
    )
    result = pe.simulate(settings)
    low, high = pe.COVERAGE_BAND
    assert (low, high) == (0.93, 0.99)
    for agent, coverage in result.coverage_population.items():
        assert low <= coverage <= high, (agent, coverage)


def test_the_same_seed_gives_identical_intervals() -> None:
    values = np.array([1, 5 / 6, 0.5, 0, 1 / 6, 2 / 3, 1, 0.5] * 2 + [1 / 3, 0, 1, 5 / 6])
    first = bootstrap.cluster_interval(values, seed=20261124)
    assert bootstrap.cluster_interval(values, seed=20261124) == first
    assert bootstrap.cluster_interval(values.copy(), seed=20261124) == first
    # Another seed draws other resamples (its interval may still land on the same values).
    draw = bootstrap.resample_indices
    assert np.array_equal(
        draw(np.random.default_rng(7), 20, 50), draw(np.random.default_rng(7), 20, 50)
    )
    assert not np.array_equal(
        draw(np.random.default_rng(7), 20, 50), draw(np.random.default_rng(8), 20, 50)
    )


def test_one_set_of_indices_resamples_every_agent_the_same_way() -> None:
    a = np.array([1.0, 0.5, 0.0, 1.0, 0.5])
    b = np.array([0.5, 0.5, 0.0, 0.5, 0.0])
    indices = bootstrap.resample_indices(np.random.default_rng(3), 5, 400)
    diff = bootstrap.replicates(a, indices) - bootstrap.replicates(b, indices)
    np.testing.assert_allclose(diff, bootstrap.replicates(a - b, indices))
    assert bootstrap.interval_from_indices(a - b, indices) == pytest.approx(
        bootstrap.percentile_interval(diff), abs=1e-12
    )


def test_the_interval_is_numpys_central_percentiles_of_task_resamples() -> None:
    values = np.array([0.0, 1.0, 0.5, 0.25])
    rng = np.random.default_rng(11)
    indices = bootstrap.resample_indices(rng, 4, 1000)
    by_hand = [float(values[row].mean()) for row in indices]
    low, high = np.percentile(by_hand, [2.5, 97.5])
    assert bootstrap.interval_from_indices(values, indices) == (float(low), float(high))


@given(
    st.lists(st.sampled_from([0, 1 / 6, 1 / 3, 1 / 2, 2 / 3, 5 / 6, 1]), min_size=1, max_size=25),
    st.integers(0, 2**32),
)
def test_the_interval_lies_within_the_task_values(values: list[float], seed: int) -> None:
    low, high = bootstrap.cluster_interval(values, seed=seed, resamples=300)
    assert min(values) - 1e-12 <= low <= high <= max(values) + 1e-12


def test_a_single_task_or_a_constant_bank_gives_a_point_interval() -> None:
    assert bootstrap.cluster_interval([0.5], seed=1, resamples=50) == (0.5, 0.5)
    assert bootstrap.cluster_interval([1.0] * 20, seed=1, resamples=50) == (1.0, 1.0)


def test_an_empty_bank_or_mismatched_indices_are_refused() -> None:
    with pytest.raises(ValueError, match="at least one task"):
        bootstrap.cluster_interval([], seed=1)
    with pytest.raises(ValueError, match="indices per resample"):
        bootstrap.replicates([1.0, 0.0], np.zeros((3, 4), dtype=np.int64))


# --- Calibration --------------------------------------------------------------------------------


def test_the_population_rate_is_the_power_scripts_and_the_mix_weighted_rate_without_spread() -> (
    None
):
    rates, mix, sigma = (0.75, 0.5, 0.3), (7, 7, 6), 0.7
    assert population_rate(rates, mix, sigma) == pe.population_rate(rates, mix, sigma)
    assert population_rate(rates, mix, 0.0) == pytest.approx(
        (0.75 * 7 + 0.5 * 7 + 0.3 * 6) / 20, abs=1e-12
    )


def test_the_bank_rate_is_the_mean_true_rate() -> None:
    assert bank_rate([0.2, 0.4, 0.9]) == pytest.approx(0.5)
    with pytest.raises(ValueError, match="no tasks"):
        bank_rate([])
