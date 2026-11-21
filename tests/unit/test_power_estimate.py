"""The power script is deterministic, writes only between its markers, and the table committed in
design.md 7.7 is exactly what it produces and meets the targets (phases.md P1-8, D8, D30)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from scipy.special import expit, logit

from scripts import power_estimate as pe

SMALL = pe.Settings(runs=40, resamples=200)


def committed_table() -> str:
    text = pe.DESIGN_MD.read_text()
    start = text.index(pe.START_MARKER) + len(pe.START_MARKER)
    return text[start : text.index(pe.END_MARKER)].strip("\n")


def test_the_same_seed_gives_the_same_table() -> None:
    assert pe.render(pe.simulate(SMALL)) == pe.render(pe.simulate(SMALL))


def test_writing_replaces_only_the_text_between_the_markers(tmp_path: Path) -> None:
    target = tmp_path / "doc.md"
    target.write_text(f"before\n{pe.START_MARKER}\nold table\n{pe.END_MARKER}\nafter\n")
    args = ["--runs", "40", "--resamples", "200", "--target", str(target)]
    pe.main(args)
    first = target.read_text()
    assert first.startswith(f"before\n{pe.START_MARKER}\n")
    assert first.endswith(f"\n{pe.END_MARKER}\nafter\n")
    assert "old table" not in first
    assert pe.render(pe.simulate(SMALL)) in first
    pe.main(args)
    assert target.read_text() == first  # idempotent


@pytest.mark.parametrize(
    "text",
    [
        "no markers at all",
        f"{pe.START_MARKER}\nonly a start",
        f"{pe.END_MARKER}\n{pe.START_MARKER}\n",
        f"{pe.START_MARKER}\n{pe.START_MARKER}\n{pe.END_MARKER}\n",
    ],
)
def test_missing_duplicated_or_reversed_markers_are_refused(text: str) -> None:
    with pytest.raises(ValueError, match="marker"):
        pe.replace_between_markers(text, "table")


def test_the_population_rate_with_no_task_spread_is_the_mix_weighted_rate() -> None:
    rates, mix = (0.9, 0.7, 0.5), (7, 7, 6)
    expected = (0.9 * 7 + 0.7 * 7 + 0.5 * 6) / 20
    assert pe.population_rate(rates, mix, sigma=0.0) == pytest.approx(expected, abs=1e-12)


def test_the_population_rate_matches_monte_carlo() -> None:
    rates, mix, sigma = pe.RATES["mid"], pe.MIX, pe.SIGMA
    rng = np.random.default_rng(7)
    levels = rng.choice(3, size=2_000_000, p=np.asarray(mix) / sum(mix))
    draws = expit(logit(np.asarray(rates))[levels] + sigma * rng.standard_normal(levels.size))
    assert pe.population_rate(rates, mix, sigma) == pytest.approx(draws.mean(), abs=1e-3)


def test_percentile_interval_is_numpys_central_95_percent() -> None:
    samples = np.arange(1001, dtype=float)
    assert pe.percentile_interval(samples) == pytest.approx((25.0, 975.0), abs=1e-9)


def test_the_committed_table_is_the_scripts_output_and_meets_the_targets() -> None:
    result = pe.simulate(pe.Settings())
    assert committed_table() == pe.render(result), "run `make power` and commit design.md"
    assert result.power[("strong", "mid")] >= pe.POWER_TARGET
    low, high = pe.COVERAGE_BAND
    assert all(low <= c <= high for c in result.coverage_population.values())
