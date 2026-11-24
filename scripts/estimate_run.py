"""`make estimate`: the full run's attempts, containers at once and expected wall time (R1, D22).

- **Attempts** come from the bank and the run plan (harness/run_plan.py): every honest scripted
  agent `EPOCHS` times on every task, and each cheater once on each task where its trick applies.
- **Per-attempt wall time** comes from the timed oracle run (`make timing`): one task per
  language, three attempts at once as in the full run, read from its log in `results/timing/`.
  Every attempt of a language is assumed to take as long as that language's oracle attempt.
- **Expected wall time** is the sum over attempts of their language's time, divided by the
  attempts that run at once (D21).

The full run must fit in 6 hours (D22); this prints whether it does, and exits 1 when it does not.
It reads logs and the bank only, and never starts a run.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from inspect_ai.log import read_eval_log

from harness.run_plan import ATTEMPTS_AT_ONCE, CONTAINERS_PER_ATTEMPT, EvalPlan, full_run
from harness.tasks import LANGUAGES, REPO_ROOT, load_task

TIMING_DIR = REPO_ROOT / "results" / "timing"
LONGEST_RUN_S = 6 * 3600  # D22


class EstimateError(Exception):
    """The timing run can't give a time for every language."""


@dataclass(frozen=True)
class Estimate:
    attempts_by_eval: dict[str, int]
    attempts_by_language: dict[str, int]
    seconds_by_language: dict[str, float]
    attempts_at_once: int
    containers_at_once: int

    @property
    def attempts(self) -> int:
        return sum(self.attempts_by_eval.values())

    @property
    def wall_seconds(self) -> float:
        serial = sum(
            n * self.seconds_by_language[lang] for lang, n in self.attempts_by_language.items()
        )
        return serial / self.attempts_at_once

    @property
    def fits(self) -> bool:
        return self.wall_seconds <= LONGEST_RUN_S


def estimate(
    plans: Sequence[EvalPlan],
    seconds_by_language: Mapping[str, float],
    language_of: Mapping[str, str],
) -> Estimate:
    by_language: Counter[str] = Counter()
    for plan in plans:
        for task_id in plan.task_ids:
            by_language[language_of[task_id]] += plan.epochs
    missing = sorted(set(by_language) - set(seconds_by_language))
    if missing:
        raise EstimateError(f"the timing run has no time for {', '.join(missing)}")
    return Estimate(
        attempts_by_eval={plan.agent: plan.attempts for plan in plans},
        attempts_by_language={lang: by_language[lang] for lang in LANGUAGES if lang in by_language},
        seconds_by_language={lang: seconds_by_language[lang] for lang in by_language},
        attempts_at_once=ATTEMPTS_AT_ONCE,
        containers_at_once=ATTEMPTS_AT_ONCE * CONTAINERS_PER_ATTEMPT,
    )


def timing_from_logs(paths: Iterable[Path]) -> dict[str, float]:
    """Each language's per-attempt wall time in the timing logs: the longest of its attempts."""
    seconds: dict[str, float] = {}
    for path in paths:
        log = read_eval_log(str(path))
        if log.status != "success":
            raise EstimateError(f"{path.name}: the timing run ended {log.status}")
        for sample in log.samples or []:
            if sample.error is not None or sample.total_time is None:
                raise EstimateError(f"{path.name}: {sample.id} has no clean wall time")
            language = str((sample.metadata or {}).get("language"))
            seconds[language] = max(seconds.get(language, 0.0), float(sample.total_time))
    if not seconds:
        raise EstimateError("no timing log: run `make timing` first")
    return seconds


def clock(seconds: float) -> str:
    minutes = round(seconds / 60)
    return f"{minutes // 60} h {minutes % 60:02d} min"


def render(e: Estimate) -> str:
    lines = [
        f"Attempts: {e.attempts}",
        *(f"  {agent}: {n}" for agent, n in e.attempts_by_eval.items()),
        "Attempts by language, and each attempt's wall time from the timed oracle run:",
        *(
            f"  {lang}: {n} x {e.seconds_by_language[lang]:.0f} s"
            for lang, n in e.attempts_by_language.items()
        ),
        f"Attempts at once: {e.attempts_at_once} ({e.containers_at_once} containers at once)",
        f"Expected wall time: {clock(e.wall_seconds)} (the limit is {clock(LONGEST_RUN_S)}, D22)",
        "Fits in the limit."
        if e.fits
        else "Does NOT fit in the limit: the run size must be decided again.",
        "Assumes every task image is already built (`make validate` builds them).",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timing-dir", type=Path, default=TIMING_DIR)
    args = parser.parse_args(argv)
    plans = full_run()
    language_of = {t: load_task(t).language for plan in plans for t in plan.task_ids}
    try:
        e = estimate(plans, timing_from_logs(sorted(args.timing_dir.glob("*.eval"))), language_of)
    except EstimateError as exc:
        print(f"no estimate: {exc}")
        return 2
    print(render(e))
    return 0 if e.fits else 1


if __name__ == "__main__":
    sys.exit(main())
