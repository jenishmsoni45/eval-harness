"""The full run's plan, its run-wide 5% budget (D74), and `make estimate` (phases.md P5-3; R1,
D18, D22, D30).

The run driver is exercised with a stand-in for Inspect that stops an eval the way Inspect's
absolute `fail_on_error` does (`inspect_ai/_eval/task/error.py`): once the eval's errors reach the
cap.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from harness.agents import cheaters, outcomes
from harness.agents import run as driver
from harness.run_plan import (
    CHEATERS,
    EPOCHS,
    HONEST_AGENTS,
    MASTER_SEED,
    EvalPlan,
    allowed_exclusions,
    eval_cap,
    full_run,
)
from harness.tasks import load_task, task_ids
from scripts import estimate_run
from tests.report_logs import Bank, Planned, write_eval

# --- The plan ---------------------------------------------------------------------------------


def test_every_honest_agent_runs_6_epochs_on_every_task() -> None:
    plans = full_run()
    assert [p.agent for p in plans[:3]] == list(HONEST_AGENTS) == list(outcomes.AGENTS)
    for plan in plans[:3]:
        assert (plan.task_ids, plan.epochs) == (tuple(task_ids()), EPOCHS)
    assert EPOCHS == 6  # D30


def test_every_cheater_runs_once_on_the_tasks_its_trick_applies_to() -> None:
    plans = {p.agent: p for p in full_run()[3:]}
    assert list(plans) == list(CHEATERS)
    assert set(CHEATERS) == set(cheaters.CHEATERS)
    for name, plan in plans.items():
        assert plan.epochs == 1
        assert list(plan.task_ids) == cheaters.applicable_tasks(name, task_ids()), name


def test_the_run_has_the_planned_number_of_attempts() -> None:
    bank = task_ids()
    easy = sum(load_task(t).difficulty == "easy" for t in bank)
    total = sum(p.attempts for p in full_run())
    assert total == 3 * 6 * len(bank) + 5 * len(bank) + easy
    assert total == 3 * 6 * 20 + 5 * 20 + 7


def test_the_master_seed_is_fixed_and_reaches_the_honest_agents() -> None:
    assert MASTER_SEED == 20261124
    model = driver.model_for("mid")
    assert model.name == "mid"
    with pytest.raises(ValueError, match="no scripted agent"):
        driver.model_for("oracle-but-misspelt")


def test_the_timing_run_takes_one_task_per_language() -> None:
    tasks = driver.timing_tasks()
    assert [load_task(t).language for t in tasks] == ["python", "go", "rust"]


# --- The run-wide budget (D74) ----------------------------------------------------------------


def test_the_budget_is_5_percent_of_the_whole_run() -> None:
    assert allowed_exclusions(467) == 23
    assert allowed_exclusions(100) == 5
    assert allowed_exclusions(19) == 0
    assert eval_cap(467, 0) == 24  # an eval stops when it alone would pass the budget
    assert eval_cap(467, 20) == 4
    assert eval_cap(467, 23) == 1  # nothing left: the next excluded attempt stops the run
    assert eval_cap(467, 30) == 1


class FakeInspect:
    """Stands in for run_eval: each eval has a planned number of attempts that would end in an
    error, and stops, as Inspect does, once its errors reach `fail_on_error`."""

    def __init__(self, errors: dict[str, int]) -> None:
        self.errors = errors
        self.calls: list[dict[str, Any]] = []

    def __call__(self, model: Any, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        cap = kwargs["fail_on_error"]
        assert isinstance(cap, int)  # an absolute cap, never a fraction
        assert cap >= 1
        planned = self.errors.get(model.name, 0)
        stopped = planned >= cap
        failed = min(planned, cap)
        samples = [SimpleNamespace(error="infra")] * failed + [SimpleNamespace(error=None)] * 3
        return SimpleNamespace(status="error" if stopped else "success", samples=samples)


PLANS = (
    EvalPlan("strong", ("a", "b"), 25),
    EvalPlan("mid", ("a", "b"), 25),
    EvalPlan("edit-test", ("a", "b"), 25),
)  # 150 attempts: the run may exclude 7


def test_each_eval_gets_what_is_left_of_the_budget(tmp_path: Path) -> None:
    fake = FakeInspect({"strong": 3, "mid": 4})
    assert driver.run_full(tmp_path, PLANS, runner=fake, say=lambda _: None)
    assert [c["fail_on_error"] for c in fake.calls] == [8, 5, 1]
    assert [c["epochs"] for c in fake.calls] == [25, 25, 25]
    assert all(c["log_dir"] == str(tmp_path) for c in fake.calls)


@given(st.lists(st.integers(0, 12), min_size=3, max_size=3))
def test_the_run_stops_exactly_when_more_than_5_percent_are_excluded(errors: list[int]) -> None:
    fake = FakeInspect(dict(zip(("strong", "mid", "edit-test"), errors, strict=True)))
    finished = driver.run_full(Path("unused"), PLANS, runner=fake, say=lambda _: None)
    assert finished == (sum(errors) <= allowed_exclusions(150))
    # Evals after the one that stopped never start.
    ran = len(fake.calls)
    cumulative = [sum(errors[: i + 1]) for i in range(3)]
    expected = next((i + 1 for i, c in enumerate(cumulative) if c > 7), 3)
    assert ran == expected


def test_a_log_directory_with_logs_is_refused(tmp_path: Path) -> None:
    driver.refuse_if_not_empty(tmp_path)  # empty: fine
    (tmp_path / "old.eval").write_bytes(b"")
    with pytest.raises(SystemExit, match="already holds logs"):
        driver.refuse_if_not_empty(tmp_path)


# --- make estimate (P5-3) ---------------------------------------------------------------------


def test_the_estimate_counts_attempts_and_divides_by_the_attempts_at_once() -> None:
    plans = full_run()
    language_of = {t: load_task(t).language for t in task_ids()}
    e = estimate_run.estimate(plans, {"python": 60.0, "go": 90.0, "rust": 200.0}, language_of)
    by_language: Counter[str] = Counter()
    for plan in plans:
        for t in plan.task_ids:
            by_language[language_of[t]] += plan.epochs
    assert e.attempts == sum(p.attempts for p in plans) == 467
    assert e.attempts_by_language == dict(by_language)
    assert (e.attempts_at_once, e.containers_at_once) == (3, 6)
    serial = 60 * by_language["python"] + 90 * by_language["go"] + 200 * by_language["rust"]
    assert e.wall_seconds == pytest.approx(serial / 3)
    assert e.fits == (serial / 3 <= 6 * 3600)
    text = estimate_run.render(e)
    for needle in (
        "Attempts: 467",
        "Attempts at once: 3 (6 containers at once)",
        "Expected wall time",
    ):
        assert needle in text


def test_a_run_over_6_hours_does_not_fit() -> None:
    e = estimate_run.estimate(
        [EvalPlan("strong", ("t",), 6)], {"rust": 3 * 3600 * 1.01 + 1}, {"t": "rust"}
    )
    assert e.wall_seconds > 6 * 3600
    assert not e.fits
    assert "Does NOT fit" in estimate_run.render(e)


def test_a_language_without_a_timing_is_refused() -> None:
    with pytest.raises(estimate_run.EstimateError, match="no time for go"):
        estimate_run.estimate([EvalPlan("strong", ("t",), 1)], {"python": 1.0}, {"t": "go"})


def test_the_timing_comes_from_the_timing_logs(tmp_path: Path) -> None:
    bank = Bank({"p": ("easy", "python"), "g": ("easy", "go"), "r": ("hard", "rust")})
    log = write_eval(tmp_path, "oracle", bank, {(t, 1): Planned(success=True) for t in bank.tasks})
    seconds = estimate_run.timing_from_logs(sorted(tmp_path.glob("*.eval")))
    assert set(seconds) == {"python", "go", "rust"}
    by_id = {str(s.id): s.total_time for s in log.samples or []}
    assert seconds["rust"] == by_id["r"]


def test_a_timing_log_with_a_failed_attempt_is_refused(tmp_path: Path) -> None:
    bank = Bank({"p": ("easy", "python")})
    excluded = {("p", 1): Planned(success=True, infra_failures=3)}
    write_eval(tmp_path, "oracle", bank, excluded, fail_on_error=10)  # the eval itself finishes
    with pytest.raises(estimate_run.EstimateError, match="no clean wall time"):
        estimate_run.timing_from_logs(sorted(tmp_path.glob("*.eval")))
    with pytest.raises(estimate_run.EstimateError, match="make timing"):
        estimate_run.timing_from_logs([])
