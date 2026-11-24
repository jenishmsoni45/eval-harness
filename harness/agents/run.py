"""`make timing` and `make eval`: the scripted agents on the bank (design.md 6 and 8; D18, D19,
D74, R1).

- **timing:** the oracle on one task per language, three attempts at once, logged to
  `results/timing/`. `make estimate` reads its per-attempt wall times (phases.md, Phase 5).
- **eval:** the full run of harness/run_plan.py, one eval per agent or cheater, logged to
  `results/logs/` (D19). Each eval gets an absolute `fail_on_error`: what is left of the run's 5%
  budget of excluded attempts, plus one (D74). An eval that does not finish stops the run, and the
  report marks the run invalid.

Neither command deletes anything: a log directory that already holds logs is refused, so two
runs never mix.

    python -m harness.agents.run timing
    python -m harness.agents.run eval
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from inspect_ai.log import EvalLog
from inspect_ai.model import Model

from harness.agents.cheaters import CHEATERS, cheater_model
from harness.agents.honest import honest_model, oracle_model
from harness.eval import run_eval
from harness.run_plan import (
    ATTEMPTS_AT_ONCE,
    HONEST_AGENTS,
    MASTER_SEED,
    EvalPlan,
    allowed_exclusions,
    eval_cap,
    full_run,
)
from harness.tasks import LANGUAGES, REPO_ROOT, load_task, task_ids

LOG_DIR = REPO_ROOT / "results" / "logs"
TIMING_DIR = REPO_ROOT / "results" / "timing"

Runner = Callable[..., EvalLog]


def model_for(agent: str) -> Model:
    if agent in HONEST_AGENTS:
        return honest_model(agent, master_seed=MASTER_SEED)
    if agent in CHEATERS:
        return cheater_model(agent)
    raise ValueError(f"no scripted agent or cheater named {agent!r}")


def excluded(log: EvalLog) -> int:
    """Samples that still ended in an error after their retries (design.md 8)."""
    return sum(1 for sample in log.samples or [] if sample.error is not None)


def run_full(
    log_dir: Path,
    plans: Sequence[EvalPlan] | None = None,
    runner: Runner = run_eval,
    say: Callable[[str], None] = print,
) -> bool:
    """Runs every eval of the plan in order; True when every eval finished. Stops at the first
    eval that did not finish, which happens when the run's exclusions pass its budget."""
    plans = full_run() if plans is None else tuple(plans)
    total = sum(plan.attempts for plan in plans)
    so_far = 0
    say(
        f"{len(plans)} evals, {total} attempts; the run may exclude at most "
        f"{allowed_exclusions(total)} (D74)"
    )
    for plan in plans:
        cap = eval_cap(total, so_far)
        say(f"{plan.agent}: {plan.attempts} attempts, stops at {cap} excluded")
        log = runner(
            model_for(plan.agent),
            task_ids=list(plan.task_ids),
            epochs=plan.epochs,
            log_dir=str(log_dir),
            fail_on_error=cap,
        )
        so_far += excluded(log)
        if log.status != "success":
            say(f"{plan.agent}: the eval ended {log.status}; the run stops here and is invalid")
            return False
    say(f"done: {so_far} of {total} attempts excluded")
    return True


def timing_tasks() -> list[str]:
    """One task per language: the first of each in the bank's order."""
    bank = task_ids()
    return [next(t for t in bank if load_task(t).language == lang) for lang in LANGUAGES]


def run_timing(log_dir: Path, runner: Runner = run_eval) -> EvalLog:
    return runner(
        oracle_model(),
        task_ids=timing_tasks(),
        epochs=1,
        log_dir=str(log_dir),
        max_samples=ATTEMPTS_AT_ONCE,
    )


def refuse_if_not_empty(log_dir: Path) -> None:
    if log_dir.exists() and any(log_dir.glob("*.eval")):
        sys.exit(f"{log_dir} already holds logs; move them away first, so two runs never mix")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["timing", "eval"])
    args = parser.parse_args(argv)
    if args.command == "timing":
        refuse_if_not_empty(TIMING_DIR)
        log = run_timing(TIMING_DIR)
        print(f"timing run {log.status}: {log.location}")
        return 0 if log.status == "success" else 1
    refuse_if_not_empty(LOG_DIR)
    return 0 if run_full(LOG_DIR) else 1


if __name__ == "__main__":
    sys.exit(main())
