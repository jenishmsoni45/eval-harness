"""`make report`: the full run's report, rebuilt from the saved logs alone (design.md 7, 8, 9; R2,
R3, R5, R12-R14; D18, D19, D74, D78).

It reads every Inspect log in `results/logs/` and nothing else: no agent code (R4), no task
files, no network. First it decides whether the run is valid. A run is invalid when more than 5% of
its planned attempts are excluded (an attempt that failed 3 times, or one missing because its eval
stopped) or when any of its evals did not finish (D18, D74). An invalid run's report says so and
why, gives the operational numbers, and presents no pass rates, intervals or comparisons; `make
report` then exits 1 (P5-7).

For a valid run it gives:
- each honest agent's pass@1 with its 95% cluster-bootstrap interval, overall and by level and
  language, and pass@k for k = 1 to the attempts per task (design.md 7.2, 7.3);
- the paired differences between agents with their intervals, worded per design.md 7.4;
- the calibration check against each agent's bank rate and population rate (7.5);
- each task's success fraction per agent and the spread within each level (7.8);
- integrity: for every agent and cheater, the share of attempts and of apparent passes that got
  each flag;
- the infrastructure-failure rate, retried attempts, task flakes, median steps, wall time per
  attempt and total run time.

Output is deterministic: rows are sorted, numbers have a fixed format, the bootstrap seed is fixed
here, and nothing depends on when the report is built (design.md 9).

    python -m stats.report                       # results/logs/ -> results/reports/report.md
    python -m stats.report --logs DIR --out FILE
"""

from __future__ import annotations

import argparse
import hashlib
import statistics
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any

from inspect_ai.log import EvalLog, EvalSample, read_eval_log

from stats.bootstrap import CONFIDENCE, RESAMPLES, cluster_interval
from stats.calibration import bank_rate, population_rate
from stats.passk import mean_pass_at_k

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "results" / "logs"
REPORT = ROOT / "results" / "reports" / "report.md"

SCORER = "hidden_tests"  # the harness's scorer, whose metadata is the attempt's record
BOOTSTRAP_SEED = 20261124  # design.md 9: fixed in the report's configuration
EXCLUDED_SHARE = 0.05  # D18
LEVELS = ("easy", "medium", "hard")
LANGUAGES = ("python", "go", "rust")
# design.md 7.4: the honest agents in the order shown, and the primary comparison, fixed before
# the run. The other pairs are secondary.
HONEST_ORDER = ("strong", "mid", "weak")
PRIMARY = ("strong", "mid")
MODEL_PREFIX = "mockllm/"


# --- Reading the logs ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Attempt:
    agent: str
    task_id: str
    epoch: int
    difficulty: str
    language: str
    excluded: bool  # still an error after its retries (design.md 8)
    retries: int  # infrastructure failures retried before the final result (R5)
    record: dict[str, Any]  # the scorer's record; empty when excluded
    wall_seconds: float | None

    @property
    def flake(self) -> bool:
        return bool(self.record.get("task_flake"))

    @property
    def scored(self) -> bool:
        """Counted in the statistics: not excluded and not a task flake (design.md 8, D12)."""
        return not self.excluded and not self.flake

    @property
    def success(self) -> bool:
        return bool(self.record.get("success"))

    @property
    def info(self) -> dict[str, Any]:
        agent = self.record.get("agent")
        return agent if isinstance(agent, dict) else {}


@dataclass(frozen=True)
class EvalRun:
    agent: str
    file: str
    sha256: str
    status: str
    planned: int
    attempts: tuple[Attempt, ...]
    started: datetime | None
    completed: datetime | None

    @property
    def missing(self) -> int:
        return max(self.planned - len(self.attempts), 0)


@dataclass(frozen=True)
class Run:
    evals: tuple[EvalRun, ...]

    @property
    def attempts(self) -> list[Attempt]:
        return [a for e in self.evals for a in e.attempts]

    @property
    def planned(self) -> int:
        return sum(e.planned for e in self.evals)

    @property
    def excluded(self) -> int:
        return sum(a.excluded for a in self.attempts) + sum(e.missing for e in self.evals)

    def invalid_reasons(self) -> list[str]:
        reasons = []
        if not self.evals:
            reasons.append("there are no logs")
        allowed = int(self.planned * EXCLUDED_SHARE)
        if self.excluded > allowed:
            reasons.append(
                f"{self.excluded} of {self.planned} planned attempts are excluded, more than 5% "
                f"(at most {allowed}, D18)"
            )
        reasons += [
            f"the eval of {e.agent} ({e.file}) ended {e.status}, not success"
            for e in self.evals
            if e.status != "success"
        ]
        return reasons


def _agent_name(log: EvalLog) -> str:
    model = log.eval.model
    return model.removeprefix(MODEL_PREFIX)


def _when(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _attempt(agent: str, sample: EvalSample) -> Attempt:
    metadata = sample.metadata or {}
    score = (sample.scores or {}).get(SCORER)
    excluded = sample.error is not None or score is None
    record = dict(score.metadata or {}) if score is not None and not excluded else {}
    return Attempt(
        agent=agent,
        task_id=str(sample.id),
        epoch=int(sample.epoch),
        difficulty=str(metadata.get("difficulty")),
        language=str(metadata.get("language")),
        excluded=excluded,
        retries=len(sample.error_retries or []),
        record=record,
        wall_seconds=sample.total_time,
    )


def read_run(paths: Iterable[Path]) -> Run:
    evals = []
    for path in sorted(paths, key=lambda p: p.name):
        log = read_eval_log(str(path))
        agent = _agent_name(log)
        epochs = log.eval.config.epochs or 1
        evals.append(
            EvalRun(
                agent=agent,
                file=path.name,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                status=log.status,
                planned=(log.eval.dataset.samples or 0) * epochs,
                attempts=tuple(
                    sorted(
                        (_attempt(agent, s) for s in log.samples or []),
                        key=lambda a: (a.task_id, a.epoch),
                    )
                ),
                started=_when(log.stats.started_at),
                completed=_when(log.stats.completed_at),
            )
        )
    return Run(tuple(evals))


# --- Statistics ---------------------------------------------------------------------------------


@dataclass
class AgentStats:
    name: str
    # task -> (attempts scored, successes), over scored attempts only
    counts: dict[str, tuple[int, int]] = field(default_factory=dict)
    difficulty: dict[str, str] = field(default_factory=dict)
    language: dict[str, str] = field(default_factory=dict)
    true_rate: dict[str, float] = field(default_factory=dict)
    level_rate: dict[str, float] = field(default_factory=dict)
    sigma: float | None = None

    def tasks(self, level: str | None = None, language: str | None = None) -> list[str]:
        return sorted(
            t
            for t in self.counts
            if (level is None or self.difficulty[t] == level)
            and (language is None or self.language[t] == language)
        )

    def fractions(self, tasks: Sequence[str]) -> list[float]:
        return [self.counts[t][1] / self.counts[t][0] for t in tasks]


def agent_stats(attempts: Sequence[Attempt], name: str) -> AgentStats:
    s = AgentStats(name)
    by_task: dict[str, list[Attempt]] = defaultdict(list)
    for a in attempts:
        if a.agent == name:
            by_task[a.task_id].append(a)
    for task_id, task_attempts in sorted(by_task.items()):
        first = task_attempts[0]
        s.difficulty[task_id], s.language[task_id] = first.difficulty, first.language
        scored = [a for a in task_attempts if a.scored]
        infos = [a.info for a in task_attempts if a.info.get("true_rate") is not None]
        if infos:
            s.true_rate[task_id] = float(infos[0]["true_rate"])
            s.level_rate[first.difficulty] = float(infos[0]["level_rate"])
            s.sigma = float(infos[0]["sigma"])
        if scored:
            s.counts[task_id] = (len(scored), sum(a.success for a in scored))
    return s


def honest_agents(attempts: Sequence[Attempt]) -> list[str]:
    """Agents whose records carry a true rate: the honest scripted agents (design.md 6)."""
    names = {a.agent for a in attempts if a.info.get("true_rate") is not None}
    return [n for n in HONEST_ORDER if n in names] + sorted(names - set(HONEST_ORDER))


def interval(values: Sequence[float]) -> tuple[float, float]:
    return cluster_interval(values, seed=BOOTSTRAP_SEED, resamples=RESAMPLES)


def comparison_words(first: str, second: str, low: float, high: float) -> str:
    """design.md 7.4, R3: a winner only when the paired interval excludes zero."""
    if low > 0:
        return f"{first} beats {second}"
    if high < 0:
        return f"{second} beats {first}"
    return f"the data cannot tell {first} and {second} apart"


# --- Rendering ----------------------------------------------------------------------------------


def _f(x: float) -> str:
    return f"{x:.3f}"


def _ci(low: float, high: float) -> str:
    return f"[{_f(low)}, {_f(high)}]"


def _table(header: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return lines


def _clock(seconds: float) -> str:
    minutes = round(seconds / 60)
    return f"{minutes // 60} h {minutes % 60:02d} min"


def _median(values: Sequence[float]) -> str:
    return _f(statistics.median(values)) if values else "n/a"


def logs_section(run: Run) -> list[str]:
    return [
        "## Logs",
        "",
        *_table(
            ("Eval", "Log file", "SHA-256", "Status", "Planned", "Logged"),
            (
                (e.agent, f"`{e.file}`", f"`{e.sha256[:16]}`", e.status, e.planned, len(e.attempts))
                for e in run.evals
            ),
        ),
        "",
    ]


def operations_section(run: Run) -> list[str]:
    attempts = run.attempts
    retried = sum(1 for a in attempts if a.retries > 0 and not a.excluded)
    flakes = sorted((a.agent, a.task_id, a.epoch) for a in attempts if a.flake)
    rate = run.excluded / run.planned if run.planned else 0.0
    starts = [e.started for e in run.evals if e.started]
    ends = [e.completed for e in run.evals if e.completed]
    lines = [
        "## Operations",
        "",
        f"- Planned attempts: {run.planned}; logged: {len(attempts)}.",
        f"- Infrastructure-failure rate: {run.excluded} of {run.planned} attempts excluded "
        f"({_f(rate)}); an attempt is excluded after 3 infrastructure failures, and a missing "
        "attempt counts as excluded (design.md 8).",
        f"- Attempts retried after an infrastructure failure and then scored: {retried}.",
        "- Task flakes (the reference fix's changes failing the hidden tests, not counted as "
        f"agent failures, D12): {len(flakes)}"
        + (": " + ", ".join(f"{a} on {t} epoch {e}" for a, t, e in flakes) if flakes else "."),
    ]
    if starts and ends:
        total = (max(ends) - min(starts)).total_seconds()
        lines.append(f"- Total run time, from the first eval's start to the last eval's end: "
                     f"{_clock(total)}.")  # fmt: skip
    lines += [
        "",
        "Steps and wall times reflect the scripted agents' fixed scripts (design.md 6), not how "
        "long a model would take.",
        "",
        *_table(
            (
                "Agent",
                "Attempts logged",
                "Median tool calls",
                "Median wall time per attempt (s)",
                "Mean wall time per attempt (s)",
            ),
            (
                (
                    e.agent,
                    len(e.attempts),
                    _median([float(a.record["tool_calls"]) for a in e.attempts if a.record]),
                    _median([a.wall_seconds for a in e.attempts if a.wall_seconds is not None]),
                    _f(statistics.fmean(w))
                    if (w := [a.wall_seconds for a in e.attempts if a.wall_seconds is not None])
                    else "n/a",
                )
                for e in run.evals
            ),
        ),
        "",
    ]
    return lines


def apparent_pass(attempt: Attempt) -> bool:
    """design.md 4: the attempt changed at least one file and the visible tests pass after it.
    An attempt that changes nothing is never one: on medium and hard tasks the visible tests
    already pass on the bug. A link or special file the scorer rejected is a change, as in the
    scorer's own overfitting signal."""
    record = attempt.record
    changed = bool(record.get("changed_files")) or bool(record.get("rejected_files"))
    return changed and bool(record.get("visible_passed"))


def integrity_section(run: Run) -> list[str]:
    # Scored attempts only: a task flake is left out of every statistic (D78), as here.
    attempts = [a for a in run.attempts if a.scored]
    flags = sorted({f for a in attempts for f in a.record.get("flags", [])})
    agents = [e.agent for e in run.evals]
    rows = []
    for agent in agents:
        mine = [a for a in attempts if a.agent == agent]
        apparent = [a for a in mine if apparent_pass(a)]
        cells: list[object] = [agent, len(mine), len(apparent)]
        for flag in flags:
            flagged = sum(flag in a.record.get("flags", []) for a in mine)
            among = sum(flag in a.record.get("flags", []) for a in apparent)
            cells.append(
                f"{flagged} ({_f(flagged / len(mine))}); {among} of apparent passes"
                if mine
                else "n/a"
            )
        rows.append(cells)
    return [
        "## Integrity",
        "",
        "For each agent and cheater: its scored attempts, its apparent passes (attempts that "
        "changed at least one file and after which the visible tests pass, design.md 4), and for "
        "each flag the attempts that got it (with their share of the attempts) and how many of "
        "them were apparent passes.",
        "",
        *_table(("Agent", "Attempts", "Apparent passes", *flags), rows),
        "",
    ]


def results_sections(run: Run) -> list[str]:
    attempts = run.attempts
    names = honest_agents(attempts)
    agents = {n: agent_stats(attempts, n) for n in names}
    k_max = max((n for s in agents.values() for n, _ in s.counts.values()), default=0)
    lines = [
        "## pass@1 with 95% intervals",
        "",
        f"Cluster bootstrap over tasks (design.md 7.3): {RESAMPLES:,} resamples, seed "
        f"{BOOTSTRAP_SEED}, {CONFIDENCE:.0%} percentile intervals. The bank's difficulty mix is "
        "fixed while the bootstrap resamples tasks freely, so the intervals are conservative "
        "(design.md 7.6, D30).",
        "",
    ]
    groups: list[tuple[str, str | None, str | None]] = [("all tasks", None, None)]
    groups += [(level, level, None) for level in LEVELS]
    groups += [(language, None, language) for language in LANGUAGES]
    rows: list[Sequence[object]] = []
    for label, level, language in groups:
        for n in names:
            tasks = agents[n].tasks(level, language)
            if not tasks:
                continue
            fr = agents[n].fractions(tasks)
            low, high = interval(fr)
            rows.append((label, n, len(tasks), _f(statistics.fmean(fr)), _ci(low, high)))
    lines += [*_table(("Tasks", "Agent", "Tasks counted", "pass@1", "95% interval"), rows), ""]

    dropped = {
        n: sorted({a.task_id for a in attempts if a.agent == n} - set(agents[n].counts))
        for n in names
    }
    if any(dropped.values()):
        lines += [
            "Tasks left with no scored attempts, dropped (design.md 7.3): "
            + "; ".join(f"{n}: {', '.join(ts)}" for n, ts in dropped.items() if ts),
            "",
        ]

    lines += [
        f"## pass@k for k = 1 to {k_max}",
        "",
        "The unbiased estimator averaged over tasks (design.md 7.2); a task with fewer than k "
        "scored attempts is left out at that k (D78).",
        "",
    ]
    rows = []
    for label, level, language in groups:
        for n in names:
            tasks = agents[n].tasks(level, language)
            if not tasks:
                continue
            counts = [agents[n].counts[t] for t in tasks]
            values = [mean_pass_at_k(counts, k) for k in range(1, k_max + 1)]
            rows.append((label, n, *("n/a" if v is None else _f(v) for v in values)))
    lines += [*_table(("Tasks", "Agent", *(f"pass@{k}" for k in range(1, k_max + 1))), rows), ""]

    lines += [
        "## Paired comparisons",
        "",
        "The mean over tasks of the difference in success fractions, with its 95% interval from "
        "the same cluster bootstrap, resampling the same tasks for both agents (design.md 7.4). "
        "One agent is said to beat another only when the interval excludes zero.",
        "",
    ]
    pairs = list(combinations(names, 2))
    pairs.sort(key=lambda p: (p != PRIMARY, names.index(p[0]), names.index(p[1])))
    rows = []
    for first, second in pairs:
        common = sorted(set(agents[first].counts) & set(agents[second].counts))
        if not common:
            continue
        d = [
            a - b
            for a, b in zip(
                agents[first].fractions(common), agents[second].fractions(common), strict=True
            )
        ]
        low, high = interval(d)
        role = (
            "primary"
            if (first, second) == PRIMARY
            else "secondary, not adjusted for multiple comparisons"
        )
        rows.append(
            (
                f"{first} vs {second}",
                role,
                len(common),
                _f(statistics.fmean(d)),
                _ci(low, high),
                comparison_words(first, second, low, high),
            )
        )
    lines += [
        *_table(("Pair", "Comparison", "Tasks", "Difference", "95% interval", "Conclusion"), rows),
        "",
    ]

    lines += [
        "## Calibration",
        "",
        "Each agent's bank rate (the mean of its true rate over the tasks) and population rate "
        "(the expected true rate over tasks drawn with the bank's difficulty mix), both from what "
        "the agents logged (design.md 7.1, 7.5). A correct 95% interval still misses 5% of the "
        "time, so one miss among the agents is not evidence of a bug; the coverage simulation "
        "(design.md 7.6) is.",
        "",
    ]
    rows = []
    for n in names:
        s = agents[n]
        tasks = s.tasks()
        if not tasks or s.sigma is None:
            continue
        fr = s.fractions(tasks)
        low, high = interval(fr)
        mix = [sum(1 for t in tasks if s.difficulty[t] == lvl) for lvl in LEVELS]
        rates = [s.level_rate.get(lvl, 0.5) for lvl in LEVELS]
        pop = population_rate(rates, mix, s.sigma)
        bank = bank_rate([s.true_rate[t] for t in tasks])
        rows.append(
            (
                n,
                _f(bank),
                _f(pop),
                _f(statistics.fmean(fr)),
                _ci(low, high),
                "yes" if low <= bank <= high else "no",
                "yes" if low <= pop <= high else "no",
            )
        )
    lines += [
        *_table(
            (
                "Agent",
                "Bank rate",
                "Population rate",
                "pass@1",
                "95% interval",
                "Covers the bank rate",
                "Covers the population rate",
            ),
            rows,
        ),
        "",
    ]

    lines += [
        "## Per-task success",
        "",
        "Each task's success fraction per agent, and the spread (standard deviation) of the task "
        "fractions within each level: the between-task variance that makes the task-level "
        "interval wider than an attempt-level one (design.md 7.8).",
        "",
    ]
    all_tasks = sorted({t for s in agents.values() for t in s.counts})
    level_of = {t: lvl for s in agents.values() for t, lvl in s.difficulty.items()}
    language_of = {t: lang for s in agents.values() for t, lang in s.language.items()}
    rows = []
    for t in all_tasks:
        cells: list[object] = [t, level_of[t], language_of[t]]
        for n in names:
            if t in agents[n].counts:
                tried, won = agents[n].counts[t]
                cells.append(f"{won}/{tried}")
            else:
                cells.append("n/a")
        rows.append(cells)
    lines += [*_table(("Task", "Level", "Language", *names), rows), ""]
    rows = []
    for lvl in LEVELS:
        cells = [lvl]
        for n in names:
            fr = agents[n].fractions(agents[n].tasks(lvl))
            cells.append(_f(statistics.pstdev(fr)) if len(fr) > 1 else "n/a")
        rows.append(cells)
    lines += [*_table(("Level", *(f"{n} spread" for n in names)), rows), ""]
    return lines


def render(run: Run) -> str:
    reasons = run.invalid_reasons()
    lines = ["# Full scripted run", ""]
    lines += [
        "Built by `make report` (`python -m stats.report`) from the logs in `results/logs/` alone; "
        "every number below comes from that script and those logs (R13).",
        "",
    ]
    if reasons:
        lines += [
            "## This run is invalid",
            "",
            "Its numbers are not presented as results (D18, D74):",
            "",
            *(f"- {r}" for r in reasons),
            "",
        ]
        lines += logs_section(run) + operations_section(run)
        return "\n".join(lines).rstrip("\n") + "\n"
    lines += logs_section(run) + results_sections(run) + integrity_section(run)
    lines += operations_section(run)
    return "\n".join(lines).rstrip("\n") + "\n"


def build(log_dir: Path, out: Path) -> bool:
    """Writes the report; True when the run is valid."""
    run = read_run(log_dir.glob("*.eval"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(run))
    return not run.invalid_reasons()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--logs", type=Path, default=LOG_DIR)
    parser.add_argument("--out", type=Path, default=REPORT)
    args = parser.parse_args(argv)
    if not any(args.logs.glob("*.eval")):
        print(f"no logs in {args.logs}: nothing to report")
        return 2
    valid = build(args.logs, args.out)
    print(f"wrote {args.out}" + ("" if valid else " (the run is invalid; no results presented)"))
    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())
