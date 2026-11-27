"""The report (phases.md P5-6, P5-7; design.md 7, 8, 9; R2, R3, R13, D18, D74): it is rebuilt
byte for byte from saved logs alone, its numbers are the statistics modules' on the logged
attempts, and it refuses to present an invalid run as results.

The logs are real Inspect logs written in-process by tests/report_logs.py.
"""

from __future__ import annotations

import ast
import statistics
from pathlib import Path

import pytest

from stats import report
from stats.bootstrap import cluster_interval
from stats.calibration import population_rate
from stats.passk import mean_pass_at_k
from tests.report_logs import Bank, Planned, honest_info, write_eval

BANK = Bank(
    {
        "t-easy-py": ("easy", "python"),
        "t-easy-go": ("easy", "go"),
        "t-med-py": ("medium", "python"),
        "t-med-rs": ("medium", "rust"),
        "t-hard-go": ("hard", "go"),
        "t-hard-rs": ("hard", "rust"),
    }
)
RATES = {
    "strong": {"easy": 0.9, "medium": 0.7, "hard": 0.5},
    "mid": {"easy": 0.75, "medium": 0.5, "hard": 0.3},
}
EPOCHS = 4
# Successes per task out of EPOCHS, per agent.
TASKS = ("t-easy-py", "t-easy-go", "t-med-py", "t-med-rs", "t-hard-go", "t-hard-rs")
WINS = {
    "strong": dict(zip(TASKS, (4, 4, 3, 3, 2, 3), strict=True)),
    "mid": dict(zip(TASKS, (3, 2, 2, 1, 0, 1), strict=True)),
}


def plans_for(agent: str) -> dict[tuple[str, int], Planned]:
    return {
        (t, e): Planned(success=e <= WINS[agent][t])
        for t in BANK.tasks
        for e in range(1, EPOCHS + 1)
    }


def valid_run(log_dir: Path) -> None:
    for agent in RATES:
        write_eval(log_dir, agent, BANK, plans_for(agent), honest_info(agent, RATES[agent], BANK))
    cheats = {(t, 1): Planned(success=False, flags=("protected_path",)) for t in BANK.tasks}
    write_eval(log_dir, "edit-test", BANK, cheats)


@pytest.fixture(scope="module")
def valid_logs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    log_dir = tmp_path_factory.mktemp("valid")
    valid_run(log_dir)
    return log_dir


def built(log_dir: Path, tmp_path: Path) -> str:
    out = tmp_path / "report.md"
    report.build(log_dir, out)
    return out.read_text()


def row(text: str, *cells: str) -> str:
    """The table row that starts with these cells."""
    prefix = "| " + " | ".join(cells) + " |"
    found = [line for line in text.splitlines() if line.startswith(prefix)]
    assert len(found) == 1, (prefix, found)
    return found[0]


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip("|").split("|")]


def section(text: str, heading: str) -> str:
    """The text of the section whose heading starts with `heading`, up to the next one."""
    start = text.index(f"\n## {heading}")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


# --- A valid run ------------------------------------------------------------------------------


def test_the_report_is_rebuilt_byte_for_byte(valid_logs: Path, tmp_path: Path) -> None:
    first = built(valid_logs, tmp_path / "a")
    assert built(valid_logs, tmp_path / "b") == first
    assert "This run is invalid" not in first


def test_pass_at_1_and_its_interval_are_the_statistics_modules(
    valid_logs: Path, tmp_path: Path
) -> None:
    text = section(built(valid_logs, tmp_path), "pass@1")
    for agent in RATES:
        fractions = [WINS[agent][t] / EPOCHS for t in sorted(BANK.tasks)]
        low, high = cluster_interval(fractions, seed=report.BOOTSTRAP_SEED)
        assert cells(row(text, "all tasks", agent)) == [
            "all tasks",
            agent,
            "6",
            f"{statistics.fmean(fractions):.3f}",
            f"[{low:.3f}, {high:.3f}]",
        ]
    # By level and by language too (R2).
    go = [WINS["strong"][t] / EPOCHS for t in ("t-easy-go", "t-hard-go")]
    assert cells(row(text, "go", "strong"))[3] == f"{statistics.fmean(go):.3f}"
    assert cells(row(text, "hard", "mid"))[2] == "2"


def test_pass_at_k_is_given_for_every_k_up_to_the_attempts(
    valid_logs: Path, tmp_path: Path
) -> None:
    text = section(built(valid_logs, tmp_path), "pass@k")
    assert f"| Tasks | Agent | {' | '.join(f'pass@{k}' for k in range(1, EPOCHS + 1))} |" in text
    counts = [(EPOCHS, WINS["mid"][t]) for t in sorted(BANK.tasks)]
    expected = [f"{mean_pass_at_k(counts, k):.3f}" for k in range(1, EPOCHS + 1)]
    assert cells(row(text, "all tasks", "mid"))[2:] == expected
    rust = [(EPOCHS, WINS["strong"][t]) for t in ("t-med-rs", "t-hard-rs")]
    assert cells(row(text, "rust", "strong"))[2:] == [
        f"{mean_pass_at_k(rust, k):.3f}" for k in range(1, EPOCHS + 1)
    ]


def test_the_primary_comparison_comes_first_and_is_worded_by_its_interval(
    valid_logs: Path, tmp_path: Path
) -> None:
    text = section(built(valid_logs, tmp_path), "Paired comparisons")
    assert text.index("strong vs mid") < text.index("strong vs weak") if "weak" in text else True
    d = [(WINS["strong"][t] - WINS["mid"][t]) / EPOCHS for t in sorted(BANK.tasks)]
    low, high = cluster_interval(d, seed=report.BOOTSTRAP_SEED)
    line = cells(row(text, "strong vs mid"))
    assert line[1:5] == ["primary", "6", f"{statistics.fmean(d):.3f}", f"[{low:.3f}, {high:.3f}]"]
    assert line[5] == report.comparison_words("strong", "mid", low, high)


def test_calibration_uses_the_logged_rates(valid_logs: Path, tmp_path: Path) -> None:
    text = section(built(valid_logs, tmp_path), "Calibration")
    tasks = sorted(BANK.tasks)
    for agent, rates in RATES.items():
        bank = statistics.fmean(rates[BANK.tasks[t][0]] for t in tasks)
        pop = population_rate([rates[lvl] for lvl in report.LEVELS], [2, 2, 2], 0.7)
        line = cells(row(text, agent, f"{bank:.3f}"))
        assert line[2] == f"{pop:.3f}"
        assert line[5] in ("yes", "no")
        assert line[6] in ("yes", "no")


def test_integrity_counts_each_flag_per_agent(valid_logs: Path, tmp_path: Path) -> None:
    text = section(built(valid_logs, tmp_path), "Integrity")
    assert cells(row(text, "edit-test", "6", "6")) == [
        "edit-test", "6", "6", "6 (1.000); 6 of apparent passes",
    ]  # fmt: skip
    assert cells(row(text, "strong", "24", "24"))[3] == "0 (0.000); 0 of apparent passes"


def test_an_attempt_that_changes_nothing_is_never_an_apparent_pass(tmp_path: Path) -> None:
    """design.md 4: on medium and hard tasks the visible tests already pass on the bug, so only
    an attempt that changed a file can be an apparent pass."""
    for agent in RATES:
        write_eval(tmp_path, agent, BANK, plans_for(agent), honest_info(agent, RATES[agent], BANK))
    searched = {
        (t, 1): Planned(success=False, flags=("snooping",), changed=False) for t in BANK.tasks
    }
    write_eval(tmp_path, "snoop", BANK, searched)
    text = section(built(tmp_path, tmp_path), "Integrity")
    assert cells(row(text, "snoop", "6", "0")) == [
        "snoop", "6", "0", "6 (1.000); 0 of apparent passes",
    ]  # fmt: skip


def test_the_logs_are_named_with_their_hashes(valid_logs: Path, tmp_path: Path) -> None:
    text = built(valid_logs, tmp_path)
    for path in sorted(valid_logs.glob("*.eval")):
        assert f"`{path.name}`" in text


# --- Comparison wording (design.md 7.4) -------------------------------------------------------


@pytest.mark.parametrize(
    ("low", "high", "words"),
    [
        (0.01, 0.3, "a beats b"),
        (-0.3, -0.01, "b beats a"),
        (-0.1, 0.2, "the data cannot tell a and b apart"),
        (
            0.0,
            0.2,
            "the data cannot tell a and b apart",
        ),  # an interval touching zero claims nothing
    ],
)
def test_a_winner_is_named_only_when_the_interval_excludes_zero(
    low: float, high: float, words: str
) -> None:
    assert report.comparison_words("a", "b", low, high) == words


# --- Exclusions, retries and flakes -----------------------------------------------------------


def test_a_retried_attempt_counts_with_its_final_result(tmp_path: Path) -> None:
    plans = plans_for("strong") | {("t-hard-go", 1): Planned(success=True, infra_failures=2)}
    write_eval(tmp_path, "strong", BANK, plans, honest_info("strong", RATES["strong"], BANK))
    run = report.read_run(tmp_path.glob("*.eval"))
    attempt = next(a for a in run.attempts if (a.task_id, a.epoch) == ("t-hard-go", 1))
    assert (attempt.excluded, attempt.retries, attempt.success) == (False, 2, True)
    assert "- Attempts retried after an infrastructure failure and then scored: 1." in render_of(
        run
    )


def test_a_task_flake_is_listed_and_left_out_of_pass_rates(tmp_path: Path) -> None:
    plans = plans_for("strong") | {("t-easy-py", 1): Planned(success=False, flake=True)}
    write_eval(tmp_path, "strong", BANK, plans, honest_info("strong", RATES["strong"], BANK))
    text = built(tmp_path, tmp_path)
    assert "D12): 1: strong on t-easy-py epoch 1" in text
    assert cells(row(text, "t-easy-py", "easy", "python")) == ["t-easy-py", "easy", "python", "3/3"]


def test_a_task_flake_is_left_out_of_the_integrity_shares(tmp_path: Path) -> None:
    """D78: a flake is left out of every statistic, the integrity shares included."""
    plans = plans_for("strong")
    write_eval(tmp_path, "strong", BANK, plans, honest_info("strong", RATES["strong"], BANK))
    cheats = {(t, 1): Planned(success=False, flags=("protected_path",)) for t in BANK.tasks}
    cheats[("t-med-py", 1)] = Planned(success=False, flags=("protected_path",), flake=True)
    write_eval(tmp_path, "edit-test", BANK, cheats)
    text = section(built(tmp_path, tmp_path), "Integrity")
    assert cells(row(text, "edit-test", "5", "5")) == [
        "edit-test", "5", "5", "5 (1.000); 5 of apparent passes",
    ]  # fmt: skip


def render_of(run: report.Run) -> str:
    return report.render(run)


# --- Invalid runs (P5-7) ----------------------------------------------------------------------

RESULT_HEADINGS = ("## pass@1", "## pass@k", "## Paired comparisons", "## Calibration", "beats")


def assert_no_results(text: str) -> None:
    assert "## This run is invalid" in text
    for heading in RESULT_HEADINGS:
        assert heading not in text


def test_more_than_5_percent_excluded_makes_the_run_invalid(tmp_path: Path) -> None:
    # 24 planned attempts may exclude 1 (5%); exclude 2.
    plans = plans_for("strong") | {
        ("t-med-py", 1): Planned(success=True, infra_failures=3),
        ("t-med-rs", 2): Planned(success=True, infra_failures=3),
    }
    write_eval(tmp_path, "strong", BANK, plans, honest_info("strong", RATES["strong"], BANK))
    text = built(tmp_path, tmp_path)
    assert_no_results(text)
    assert "2 of 24 planned attempts are excluded, more than 5% (at most 1, D18)" in text
    assert report.main(["--logs", str(tmp_path), "--out", str(tmp_path / "again.md")]) == 1


def test_exactly_5_percent_excluded_is_still_valid(tmp_path: Path) -> None:
    write_eval(
        tmp_path, "strong", BANK, plans_for("strong"), honest_info("strong", RATES["strong"], BANK)
    )
    plans = plans_for("mid") | {("t-med-py", 1): Planned(success=True, infra_failures=3)}
    write_eval(tmp_path, "mid", BANK, plans, honest_info("mid", RATES["mid"], BANK))
    run = report.read_run(tmp_path.glob("*.eval"))
    assert (run.excluded, run.planned, run.invalid_reasons()) == (1, 48, [])
    # The excluded attempt (epoch 1, a success) is dropped before resampling: t-med-py counts
    # epochs 2 to 4 for mid, of which epoch 2 succeeded.
    assert "| t-med-py | medium | python | 3/4 | 1/3 |" in report.render(run)


def test_an_eval_that_did_not_finish_makes_the_run_invalid(tmp_path: Path) -> None:
    # An absolute cap of 1 stops the eval at its first excluded attempt (D74).
    plans = plans_for("strong") | {("t-easy-go", 2): Planned(success=True, infra_failures=3)}
    log = write_eval(
        tmp_path,
        "strong",
        BANK,
        plans,
        honest_info("strong", RATES["strong"], BANK),
        fail_on_error=1,
    )
    assert log.status == "error"
    text = built(tmp_path, tmp_path)
    assert_no_results(text)
    assert "the eval of strong" in text
    assert "ended error, not success" in text


def test_no_logs_is_refused(tmp_path: Path) -> None:
    assert report.main(["--logs", str(tmp_path), "--out", str(tmp_path / "r.md")]) == 2
    assert not (tmp_path / "r.md").exists()
    assert report.Run(()).invalid_reasons() == ["there are no logs"]


# --- The committed report (R13) ---------------------------------------------------------------


def test_the_committed_report_is_the_committed_logs_rebuilt(tmp_path: Path) -> None:
    logs = sorted(report.LOG_DIR.glob("*.eval"))
    if not logs:
        assert not report.REPORT.exists(), "a report is committed without the logs it came from"
        return
    out = tmp_path / "report.md"
    report.build(report.LOG_DIR, out)
    assert out.read_text() == report.REPORT.read_text(), "run `make report` and commit it"


def test_the_report_reads_nothing_but_logs() -> None:
    """architecture.md: stats/ never reads anything but saved logs; it imports no harness code."""
    for path in sorted(Path(report.__file__).parent.glob("*.py")):
        tree = ast.parse(path.read_text())
        modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + [
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
        ]
        assert not [m for m in modules if m.split(".")[0] in ("harness", "scripts", "rl")], path
