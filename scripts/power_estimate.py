"""Power and coverage simulation for the run size (design.md 7.6 and 7.7, D6, D8, D30).

Draws synthetic runs from the scripted-agent model of design.md section 6, computes the cluster
bootstrap intervals of design.md 7.3 and 7.4 for each run, and reports:

- for each agent, how often its 95% pass@1 interval covers the population rate and the bank rate;
- for each adjacent pair, how often the paired 95% interval lies above zero (power).

The table is written between the power-table markers in docs/design.md. Every random draw comes
from one seed, so the same inputs give the same table byte for byte.

Usage:
    python -m scripts.power_estimate            # full run, writes docs/design.md
    python -m scripts.power_estimate --print    # full run, prints the table only
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from scipy.special import expit, logit

DESIGN_MD = Path(__file__).resolve().parent.parent / "docs" / "design.md"
START_MARKER = "<!-- power-table:start -->"
END_MARKER = "<!-- power-table:end -->"

LEVELS = ("easy", "medium", "hard")
# D5: true success rates per difficulty level.
RATES: dict[str, tuple[float, float, float]] = {
    "strong": (0.9, 0.7, 0.5),
    "mid": (0.75, 0.5, 0.3),
    "weak": (0.5, 0.25, 0.1),
}
AGENTS = tuple(RATES)
# design.md 7.4: the primary comparison first, then the secondary adjacent pair.
COMPARISONS: tuple[tuple[str, str], ...] = (("strong", "mid"), ("mid", "weak"))
# design.md 14: per-task offset spread (logit scale) and the bank's fixed difficulty mix.
SIGMA = 0.7
MIX = (7, 7, 6)
# D30: attempts per task per agent.
ATTEMPTS = 6
# design.md 14: simulated runs and bootstrap resamples per simulated run.
RUNS = 2000
RESAMPLES = 2000
SEED = 20261120
CONFIDENCE = 0.95
# Targets (D6, D30): power for the primary comparison, and the E7 coverage band.
POWER_TARGET = 0.80
COVERAGE_BAND = (0.93, 0.99)
# Gauss-Hermite nodes for the population rate; far more than the integrand needs.
QUADRATURE_NODES = 101


@dataclass(frozen=True)
class Settings:
    runs: int = RUNS
    resamples: int = RESAMPLES
    seed: int = SEED
    sigma: float = SIGMA
    mix: tuple[int, int, int] = MIX
    attempts: int = ATTEMPTS


@dataclass(frozen=True)
class Result:
    settings: Settings
    population_rate: dict[str, float]
    coverage_population: dict[str, float]
    coverage_bank: dict[str, float]
    power: dict[tuple[str, str], float]

    def targets_met(self) -> bool:
        low, high = COVERAGE_BAND
        coverage_ok = all(low <= c <= high for c in self.coverage_population.values())
        return coverage_ok and self.power[COMPARISONS[0]] >= POWER_TARGET


def population_rate(rates: tuple[float, float, float], mix: tuple[int, ...], sigma: float) -> float:
    """design.md 7.1: the expected per-task success probability over tasks drawn with the bank's
    difficulty mix and fresh offsets, E[expit(logit(r_level) + sigma * Z)], by Gauss-Hermite
    quadrature for the standard normal Z."""
    nodes, weights = np.polynomial.hermite_e.hermegauss(QUADRATURE_NODES)
    weights = weights / weights.sum()
    per_level = [float(np.dot(weights, expit(logit(r) + sigma * nodes))) for r in rates]
    return float(np.dot(per_level, mix) / sum(mix))


def percentile_interval(samples: NDArray[np.float64]) -> tuple[float, float]:
    """The central CONFIDENCE interval of bootstrap replicates, by numpy's default (linear)
    percentile method."""
    tail = (1 - CONFIDENCE) / 2 * 100
    low, high = np.percentile(samples, [tail, 100 - tail])
    return float(low), float(high)


def simulate(settings: Settings) -> Result:
    levels = np.repeat(np.arange(len(LEVELS)), settings.mix)
    n_tasks = len(levels)
    base_logits = {a: logit(np.asarray(RATES[a]))[levels] for a in AGENTS}
    pop = {a: population_rate(RATES[a], settings.mix, settings.sigma) for a in AGENTS}

    covers_pop = dict.fromkeys(AGENTS, 0)
    covers_bank = dict.fromkeys(AGENTS, 0)
    above_zero = dict.fromkeys(COMPARISONS, 0)

    # One independent stream per simulated run, so a run's draws never depend on another's.
    for child in np.random.SeedSequence(settings.seed).spawn(settings.runs):
        rng = np.random.default_rng(child)
        z = rng.standard_normal(n_tasks)  # per-task offsets, shared by every agent (D5)
        q = {a: expit(base_logits[a] + settings.sigma * z) for a in AGENTS}
        frac = {a: rng.binomial(settings.attempts, q[a]) / settings.attempts for a in AGENTS}
        # Cluster bootstrap over tasks (D7): every agent and pair resamples the same tasks.
        idx = rng.integers(0, n_tasks, size=(settings.resamples, n_tasks))
        for a in AGENTS:
            low, high = percentile_interval(frac[a][idx].mean(axis=1))
            covers_pop[a] += low <= pop[a] <= high
            covers_bank[a] += low <= float(q[a].mean()) <= high
        for first, second in COMPARISONS:
            low, _ = percentile_interval((frac[first] - frac[second])[idx].mean(axis=1))
            above_zero[(first, second)] += low > 0

    n = settings.runs
    return Result(
        settings=settings,
        population_rate=pop,
        coverage_population={a: covers_pop[a] / n for a in AGENTS},
        coverage_bank={a: covers_bank[a] / n for a in AGENTS},
        power={pair: above_zero[pair] / n for pair in COMPARISONS},
    )


def mc_se(p: float, n: int) -> float:
    """Monte Carlo standard error of a proportion estimated from n simulated runs."""
    return float(np.sqrt(p * (1 - p) / n))


def render(result: Result) -> str:
    s = result.settings
    n = s.runs
    low, high = COVERAGE_BAND
    mix = ", ".join(f"{count} {level}" for count, level in zip(s.mix, LEVELS, strict=True))
    lines = [
        f"Generated by `scripts/power_estimate.py` (`make power`): seed {s.seed}, {n:,} "
        f"simulated runs of {sum(s.mix)} tasks ({mix}) × {s.attempts} attempts per agent, "  # noqa: RUF001
        f"σ = {s.sigma}, {s.resamples:,} bootstrap resamples per run, nominal "  # noqa: RUF001
        f"{CONFIDENCE:.0%} percentile intervals. MC s.e. is the Monte Carlo standard error "
        f"of each share.",
        "",
        "| Agent | Population rate | Coverage of population rate (MC s.e.) "
        "| Coverage of bank rate (MC s.e.) |",
        "|---|---|---|---|",
    ]
    for a in AGENTS:
        cp, cb = result.coverage_population[a], result.coverage_bank[a]
        lines.append(
            f"| {a} | {result.population_rate[a]:.3f} | {cp:.3f} ({mc_se(cp, n):.3f}) "
            f"| {cb:.3f} ({mc_se(cb, n):.3f}) |"
        )
    lines += [
        "",
        "| Comparison | Power: paired 95% interval above zero (MC s.e.) |",
        "|---|---|",
    ]
    for i, (first, second) in enumerate(COMPARISONS):
        p = result.power[(first, second)]
        label = "primary" if i == 0 else "secondary"
        lines.append(f"| {first} vs {second} ({label}) | {p:.3f} ({mc_se(p, n):.3f}) |")
    verdict = "met" if result.targets_met() else "NOT met"
    lines += [
        "",
        f"Targets: power ≥ {POWER_TARGET:.2f} for {COMPARISONS[0][0]} vs {COMPARISONS[0][1]}, "
        f"and coverage of the population rate within [{low:.2f}, {high:.2f}] for every agent. "
        f"Result: **{verdict}**.",
    ]
    return "\n".join(lines)


def replace_between_markers(text: str, block: str) -> str:
    """Replace everything between the two markers with block; the rest of text is unchanged."""
    if text.count(START_MARKER) != 1 or text.count(END_MARKER) != 1:
        raise ValueError(f"expected exactly one start marker {START_MARKER} and one end marker")
    start, end = text.index(START_MARKER), text.index(END_MARKER)
    if end < start:
        raise ValueError("the end marker comes before the start marker")
    return f"{text[:start]}{START_MARKER}\n{block}\n{text[end:]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=RUNS)
    parser.add_argument("--resamples", type=int, default=RESAMPLES)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--print", action="store_true", help="print the table, write nothing")
    parser.add_argument("--target", type=Path, default=DESIGN_MD, help="file with the markers")
    args = parser.parse_args(argv)

    result = simulate(Settings(runs=args.runs, resamples=args.resamples, seed=args.seed))
    block = render(result)
    if args.print:
        print(block)
    else:
        args.target.write_text(replace_between_markers(args.target.read_text(), block))
        print(f"wrote the power table to {args.target}")
        print(block)
    if not result.targets_met():
        print("power or coverage target not met: the run size must be decided again (D6, D30)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
