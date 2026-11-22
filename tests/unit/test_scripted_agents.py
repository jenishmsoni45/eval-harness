"""The strong, mid and weak scripted agents (D5, design.md 6, phases.md P3-5).

- Seeding: an attempt's seed is the first 8 bytes of SHA-256 over (master seed, agent, task,
  epoch), and the same seed makes the same choices on a rerun.
- True rates: expit(logit(r_level) + sigma * z_task), with one standard normal offset per task
  shared by every agent, and the D5 rates (the same as the power script's).
- Outcomes: success with the true rate, and D29's failure-mode mix otherwise.
- Trajectories: the short script of design.md 6 for every outcome.
- In sandboxes: each failure mode gives its expected base, and every attempt's record carries
  the agent's true rate, seed and outcome.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import scipy.special
import scipy.stats
from inspect_ai.model import ChatMessageUser

from harness.agents import honest
from harness.agents.honest import AgentInfo, honest_model, output_at, plan
from harness.agents.outcomes import (
    AGENTS,
    FAILURE_MIX,
    LEVELS,
    RATES,
    SIGMA,
    Draw,
    Outcome,
    attempt_seed,
    draw,
    task_offset,
    true_rate,
)
from harness.agents.patches import parse_patch, plan_edits
from harness.agents.scripted import Turn, with_stable_ids
from harness.tasks import load_task, task_ids
from harness.testrun import REPO_DIR
from scripts import power_estimate
from tests.runs import base, by_task, one_task_per_language, record, tool_events

if TYPE_CHECKING:
    from inspect_ai.log import EvalLog
    from inspect_ai.model import ModelOutput

MASTER_SEED = 7


def turn(task_id: str, epoch: int = 1, step: int = 0) -> Turn:
    return Turn(task_id=task_id, epoch=epoch, step=step, messages=[ChatMessageUser(content="x")])


def calls(outputs: list[ModelOutput]) -> list[tuple[str, str | None]]:
    """(tool, text_editor command) for each output's one tool call."""
    out = []
    for output in outputs:
        [call] = output.message.tool_calls or []
        out.append(
            (call.function, call.arguments.get("command") if call.function != "bash" else None)
        )
    return out


# --- Rates and seeds ----------------------------------------------------------------------


def test_the_rates_are_d5s_and_match_the_power_script() -> None:
    assert RATES == {
        "strong": {"easy": 0.9, "medium": 0.7, "hard": 0.5},
        "mid": {"easy": 0.75, "medium": 0.5, "hard": 0.3},
        "weak": {"easy": 0.5, "medium": 0.25, "hard": 0.1},
    }
    assert {a: tuple(RATES[a][level] for level in LEVELS) for a in AGENTS} == power_estimate.RATES
    assert power_estimate.LEVELS == LEVELS
    assert SIGMA == power_estimate.SIGMA == 0.7


def test_the_failure_mix_is_design_14s() -> None:
    assert [(o.value, w) for o, w in FAILURE_MIX] == [
        ("wrong", 0.4),
        ("partial", 0.3),
        ("give_up", 0.2),
        ("out_of_steps", 0.1),
    ]
    assert sum(w for _, w in FAILURE_MIX) == pytest.approx(1.0)


def length_prefixed_sha256(*parts: object) -> int:
    digest = hashlib.sha256()
    for part in parts:
        data = str(part).encode()
        digest.update(len(data).to_bytes(8, "big") + data)
    return int.from_bytes(digest.digest()[:8], "big")


def test_the_attempt_seed_is_the_first_8_bytes_of_sha256() -> None:
    seed = attempt_seed(MASTER_SEED, "strong", "risk-001", 3)
    assert seed == length_prefixed_sha256(MASTER_SEED, "strong", "risk-001", 3)
    assert 0 <= seed < 2**64
    others = {
        attempt_seed(MASTER_SEED + 1, "strong", "risk-001", 3),
        attempt_seed(MASTER_SEED, "mid", "risk-001", 3),
        attempt_seed(MASTER_SEED, "strong", "risk-002", 3),
        attempt_seed(MASTER_SEED, "strong", "risk-001", 4),
    }
    assert seed not in others
    assert len(others) == 4


def test_the_task_offset_is_fixed_shared_and_standard_normal() -> None:
    assert task_offset("risk-001") == task_offset("risk-001")
    offsets = [task_offset(f"synthetic-{i:05d}") for i in range(4000)]
    assert len(set(offsets)) == len(offsets)
    # A standard normal: mean 0 and sd 1 within a few standard errors, and a KS test.
    assert abs(sum(offsets) / len(offsets)) < 4 / len(offsets) ** 0.5
    assert scipy.stats.kstest(offsets, "norm").pvalue > 0.001


@pytest.mark.parametrize("task_id", task_ids())
def test_true_rates_follow_the_logit_model(task_id: str) -> None:
    task = load_task(task_id)
    z = task_offset(task_id)
    rates = {}
    for agent in AGENTS:
        expected = scipy.special.expit(
            scipy.special.logit(RATES[agent][task.difficulty]) + SIGMA * z
        )
        rates[agent] = true_rate(agent, task.difficulty, task_id)
        assert rates[agent] == pytest.approx(expected, rel=1e-12)
    # One offset shared by every agent keeps their order on every task.
    assert 0 < rates["weak"] < rates["mid"] < rates["strong"] < 1


def test_outcomes_follow_the_true_rate_and_the_failure_mix() -> None:
    rate, n = 0.3, 40_000
    draws = [draw(length_prefixed_sha256("draws", i), rate) for i in range(n)]
    assert draws[0] == draw(draws[0].seed, rate)  # the same seed, the same draw
    successes = sum(d.outcome is Outcome.SUCCESS for d in draws)
    se = (rate * (1 - rate) / n) ** 0.5
    assert abs(successes / n - rate) < 4 * se
    failures = [d.outcome for d in draws if d.outcome is not Outcome.SUCCESS]
    for outcome, weight in FAILURE_MIX:
        share = sum(f is outcome for f in failures) / len(failures)
        assert abs(share - weight) < 4 * (weight * (1 - weight) / len(failures)) ** 0.5, outcome
    assert {d.outcome for d in draw_all(1.0)} == {Outcome.SUCCESS}
    assert Outcome.SUCCESS not in {d.outcome for d in draw_all(0.0)}


def draw_all(rate: float) -> list[Draw]:
    return [draw(length_prefixed_sha256("edge", i), rate) for i in range(200)]


# --- Choices and trajectories -------------------------------------------------------------


@pytest.mark.parametrize("agent", AGENTS)
def test_a_fixed_seed_makes_the_same_choices_on_a_rerun(agent: str) -> None:
    first, second = {}, {}
    for task_id in task_ids():
        for epoch in range(1, 7):
            info = plan(agent, MASTER_SEED, turn(task_id, epoch))
            assert info == plan(agent, MASTER_SEED, turn(task_id, epoch))
            seed = attempt_seed(MASTER_SEED, agent, task_id, epoch)
            assert info == AgentInfo(
                agent,
                MASTER_SEED,
                seed,
                true_rate(agent, load_task(task_id).difficulty, task_id),
                draw(seed, info.true_rate or 0.0).outcome.value,
            )
            outcome = Outcome(info.outcome)
            first[task_id, epoch] = [output_at(agent, task_id, outcome, s) for s in range(12)]
            second[task_id, epoch] = [output_at(agent, task_id, outcome, s) for s in range(12)]
    assert {k: calls(v) for k, v in first.items()} == {k: calls(v) for k, v in second.items()}
    # The arguments and the logged call ids are identical too, not just the tools.
    for key, outputs in first.items():
        for step, (a, b) in enumerate(zip(outputs, second[key], strict=True)):
            assert with_stable_ids(a, step).message.tool_calls == (
                with_stable_ids(b, step).message.tool_calls
            )
    # Another master seed changes some outcome.
    other = {
        (t, e): plan(agent, MASTER_SEED + 1, turn(t, e)).outcome
        for t in task_ids()
        for e in range(1, 7)
    }
    assert other != {
        (t, e): plan(agent, MASTER_SEED, turn(t, e)).outcome
        for t in task_ids()
        for e in range(1, 7)
    }


def script_calls(task_id: str, outcome: Outcome, steps: int | None = None) -> list[ModelOutput]:
    n = steps if steps is not None else len(honest.script("strong", task_id, outcome))
    return [output_at("strong", task_id, outcome, s) for s in range(n)]


@pytest.mark.parametrize("task_id", task_ids())
@pytest.mark.parametrize("outcome", [Outcome.SUCCESS, Outcome.WRONG, Outcome.PARTIAL])
def test_a_fix_attempt_runs_tests_views_edits_runs_tests_and_submits(
    task_id: str, outcome: Outcome
) -> None:
    task = load_task(task_id)
    patch = task.patches[honest.PATCH_OF[outcome]].read_text()
    viewed = [fp for fp in parse_patch(patch) if not fp.new_file]
    edits = plan_edits(patch, task.repo_dir)
    outputs = script_calls(task_id, outcome)
    assert calls(outputs) == [
        ("bash", None),
        *[("text_editor", "view")] * len(viewed),
        *[("text_editor", "create" if e.old is None else "str_replace") for e in edits],
        ("bash", None),
        ("submit", None),
    ]
    editor = [o.message.tool_calls[0].arguments for o in outputs[1 + len(viewed) : -2]]  # type: ignore[index]
    assert [(a.get("old_str"), a.get("new_str", a.get("file_text"))) for a in editor] == [
        (e.old, e.new) for e in edits
    ]


@pytest.mark.parametrize("task_id", task_ids())
def test_giving_up_stops_after_viewing_and_submits_no_change(task_id: str) -> None:
    viewed = [
        fp for fp in parse_patch(load_task(task_id).solution_patch.read_text()) if not fp.new_file
    ]
    outputs = script_calls(task_id, Outcome.GIVE_UP)
    assert calls(outputs) == [
        ("bash", None),
        *[("text_editor", "view")] * len(viewed),
        ("submit", None),
    ]


@pytest.mark.parametrize("task_id", task_ids())
def test_running_out_of_steps_views_files_and_never_submits(task_id: str) -> None:
    outputs = script_calls(task_id, Outcome.OUT_OF_STEPS, steps=45)
    assert calls(outputs) == [("bash", None)] + [("text_editor", "view")] * 44


def test_running_out_of_steps_views_the_repo_when_a_fix_only_adds_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adds_a_file = "--- /dev/null\n+++ b/pkg/new.py\n@@ -0,0 +1 @@\n+X = 1\n"
    monkeypatch.setattr(honest, "_patch", lambda task, outcome: adds_a_file)
    for step in range(1, 5):
        [call] = (
            output_at("strong", "risk-001", Outcome.OUT_OF_STEPS, step).message.tool_calls or []
        )
        assert (call.function, call.arguments) == (
            "text_editor",
            {"command": "view", "path": REPO_DIR},
        )


PATCHES = ["solution.patch", "wrong.patch", "partial.patch"]


@pytest.mark.parametrize("patch_name", PATCHES)
@pytest.mark.parametrize("task_id", task_ids())
def test_every_patch_becomes_edits_equal_to_git_apply(
    task_id: str, patch_name: str, tmp_path: Path
) -> None:
    task = load_task(task_id)
    patch_path = task.patches[patch_name]
    patch = patch_path.read_text()
    shutil.copytree(task.repo_dir, tmp_path / "repo")
    subprocess.run(["git", "apply", str(patch_path)], cwd=tmp_path / "repo", check=True)
    for fp in parse_patch(patch):
        content = "" if fp.new_file else (task.repo_dir / fp.path).read_text()
        for edit in (e for e in plan_edits(patch, task.repo_dir) if e.path == fp.path):
            if edit.old is None:
                content = edit.new
                continue
            assert content.count(edit.old) == 1
            content = content.replace(edit.old, edit.new, 1)
        assert content == (tmp_path / "repo" / fp.path).read_text()


def test_only_the_three_scripted_agents_exist() -> None:
    with pytest.raises(ValueError, match="unknown scripted agent"):
        honest_model("genius")


# --- In sandboxes ---------------------------------------------------------------------------


@pytest.mark.docker
def test_each_failure_mode_gives_its_expected_base(failure_mode_runs: dict[str, EvalLog]) -> None:
    """P3-5: a wrong patch scores below 1, a partial patch strictly between 0 and 1, giving up
    and running out of steps 0; each attempt changes only what its script says."""
    for outcome, log in failure_mode_runs.items():
        for task_id, sample in by_task(log).items():
            score, changed = base(sample), record(sample)["changed_files"]
            if outcome == Outcome.WRONG:
                assert score < 1, (task_id, score)
            elif outcome == Outcome.PARTIAL:
                assert 0 < score < 1, (task_id, score)
            else:
                assert score == 0, (task_id, outcome, score)
                assert changed == []
            assert record(sample)["agent"]["outcome"] == outcome
            assert all(e.error is None for e in tool_events(sample)), (task_id, outcome)


@pytest.mark.docker
def test_wrong_and_partial_attempts_change_what_their_patch_changes(
    failure_mode_runs: dict[str, EvalLog],
) -> None:
    for outcome in (Outcome.WRONG, Outcome.PARTIAL):
        for task_id, sample in by_task(failure_mode_runs[outcome]).items():
            patch = load_task(task_id).patches[honest.PATCH_OF[outcome]].read_text()
            assert record(sample)["changed_files"] == sorted(fp.path for fp in parse_patch(patch))


@pytest.mark.docker
def test_seeded_agents_log_their_true_rate_seed_and_drawn_outcome(
    docker_engine: None, tmp_path: Path
) -> None:
    """An unforced run: each attempt's record carries the agent's true rate on the task, its
    seed and its drawn outcome, and the base agrees with the outcome."""
    from harness.eval import run_eval

    tasks = one_task_per_language()
    log = run_eval(
        honest_model("mid", master_seed=MASTER_SEED), task_ids=tasks, log_dir=str(tmp_path)
    )
    for task_id, sample in by_task(log).items():
        info = record(sample)["agent"]
        task = load_task(task_id)
        seed = attempt_seed(MASTER_SEED, "mid", task_id, sample.epoch)
        rate = true_rate("mid", task.difficulty, task_id)
        assert info == {
            "name": "mid",
            "master_seed": MASTER_SEED,
            "seed": seed,
            "true_rate": rate,
            "outcome": draw(seed, rate).outcome.value,
        }
        expected = {"success": 1.0, "give_up": 0.0, "out_of_steps": 0.0}
        if info["outcome"] in expected:
            assert base(sample) == expected[info["outcome"]]
        else:
            assert base(sample) < 1
