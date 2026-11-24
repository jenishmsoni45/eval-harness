"""The validator's mechanics (task-spec.md "Validation rules", D12, D40): the container script,
parsing a run's output, how each state is judged, consistency across runs, what V4 looks for and
which tasks a branch changed. The per-rule tests with broken fixture tasks are in
test_validation_rules.py."""

from __future__ import annotations

import base64
import subprocess
from typing import Any

import pytest

from harness.tasks import load_task
from scripts import validate_tasks
from scripts.validate_tasks import (
    Findings,
    RunResult,
    container_script,
    fixed_problems,
    leak_patterns,
    parse_output,
    partial_problems,
    run_state,
    shipped_problems,
    wrong_problems,
)

TASK = load_task("risk-001")


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def step_line(name: str, code: int, output: str = "", ms: int = 10) -> str:
    return f"@@evalh step {name} {code} {ms} {b64(output)}"


def junit(n: int) -> str:
    return "<testsuites><testsuite>" + '<testcase name="t"/>' * n + "</testsuite></testsuites>"


def run(visible: int, bug: list[int], regression_exit: int, count: int) -> RunResult:
    lines = [step_line("visible", visible), f"@@evalh report visible {b64(junit(40))}"]
    lines += [step_line(f"bug-{i}", code) for i, code in enumerate(bug)]
    lines += [step_line("regression", regression_exit, "log")]
    lines.append(f"@@evalh report regression {b64(junit(count))}")
    return parse_output(TASK, "\n".join(["noise", *lines, ""]))


def test_the_visible_tests_run_before_any_hidden_test_is_copied_in() -> None:
    """D40: for Go, the hidden tests sit in the package the visible command tests."""
    for task_id in ("risk-001", "queue-001", "vault-001"):
        script = container_script(load_task(task_id), with_patch=True)
        visible = script.index("step visible ")
        copy = script.index("cp -R /tmp/evalh-in/hidden/.")
        assert script.index("git apply /tmp/evalh-in/fix.patch") < visible < copy
        assert copy < script.index("step bug-0 ") < script.index("step regression ")


def test_the_script_runs_every_bug_test_on_its_own_and_the_regression_suite() -> None:
    script = container_script(TASK, with_patch=False)
    for i, test in enumerate(TASK.bug_tests):
        assert f"step bug-{i} pytest -p no:cacheprovider {test}" in script
    assert "--junitxml=/tmp/evalh-regression-report.xml" in script
    assert "git apply" not in script


def test_go_and_rust_runs_report_from_the_runners_own_output() -> None:
    for task_id in ("queue-001", "vault-001"):
        script = container_script(load_task(task_id), with_patch=False)
        assert "junitxml" not in script
        assert 'report regression %s\\n" "$(base64 -w0 /tmp/evalh-out)"' in script
    assert "step visible go test -json -count=1 ./internal/scheduler" in container_script(
        load_task("queue-001"), with_patch=False
    )


def test_output_is_parsed_into_results_and_times() -> None:
    result = run(0, [1, 1, 1], 0, TASK.regression_count)
    assert result.visible_exit == 0
    assert result.visible_passed == 40
    assert list(result.bug_passed.values()) == [False, False, False]
    assert result.regression_ok
    assert result.test_ms == 50
    assert result.outputs["regression"] == "log"


def test_a_missing_step_is_an_error() -> None:
    with pytest.raises(RuntimeError, match="steps"):
        parse_output(TASK, step_line("visible", 0))


def problems_of(judge: Any, visible: int, bug: list[int], regression: int, count: int) -> int:
    return len(judge(TASK, run(visible, bug, regression, count)))


def test_the_shipped_bug_must_fail_each_bug_test_and_pass_regression() -> None:
    n = TASK.regression_count
    assert problems_of(shipped_problems, 1, [1, 1, 1], 0, n) == 0
    assert problems_of(shipped_problems, 1, [1, 0, 1], 0, n) == 1
    assert problems_of(shipped_problems, 1, [1, 1, 1], 0, n - 1) == 1


def test_the_reference_fix_must_pass_everything() -> None:
    n = TASK.regression_count
    assert problems_of(fixed_problems, 0, [0, 0, 0], 0, n) == 0
    assert problems_of(fixed_problems, 1, [0, 0, 0], 0, n) == 1
    assert problems_of(fixed_problems, 0, [0, 1, 0], 0, n) == 1
    assert problems_of(fixed_problems, 0, [0, 0, 0], 1, n) == 1


def test_the_wrong_patch_must_pass_visible_and_regression_and_fail_a_bug_test() -> None:
    n = TASK.regression_count
    assert problems_of(wrong_problems, 0, [0, 1, 1], 0, n) == 0
    assert problems_of(wrong_problems, 0, [1, 1, 1], 0, n) == 0
    assert problems_of(wrong_problems, 0, [0, 0, 0], 0, n) == 1
    assert problems_of(wrong_problems, 1, [1, 1, 1], 0, n) == 1
    assert problems_of(wrong_problems, 0, [1, 1, 1], 0, n + 1) == 1


def test_the_partial_patch_must_pass_some_but_not_all_bug_tests() -> None:
    n = TASK.regression_count
    assert problems_of(partial_problems, 1, [0, 1, 1], 0, n) == 0
    assert problems_of(partial_problems, 1, [1, 1, 1], 0, n) == 1
    assert problems_of(partial_problems, 1, [0, 0, 0], 0, n) == 1
    assert problems_of(partial_problems, 1, [0, 1, 1], 1, n) == 1


def test_runs_that_differ_are_flagged_as_flaky(monkeypatch: pytest.MonkeyPatch) -> None:
    """D12: any inconsistent result rejects the task, even if each run alone is acceptable."""
    results = iter(
        [run(0, [0, 1, 1], 0, TASK.regression_count), run(0, [1, 0, 1], 0, TASK.regression_count)]
    )
    monkeypatch.setattr(validate_tasks, "run_once", lambda *args: next(results))
    findings = Findings()
    run_state(TASK, "image", "partial patch", 2, findings)
    assert findings.problems() == ["V8: partial patch: results differ between runs (flaky)"]


def test_v4_looks_for_the_canary_bug_test_names_and_new_patch_lines() -> None:
    patterns = leak_patterns(TASK)
    assert TASK.canary in patterns
    assert "test_an_event_at_t_minus_w_counts_and_one_at_t_does_not" in patterns
    assert "return t_ms - width_ms <= time_ms < t_ms" in patterns
    # A line the patch only keeps, or a short one, is not hidden material.
    assert "values: dict[str, int] = {}" not in patterns
    assert 'if window == "1h":' not in patterns
    rust = leak_patterns(load_task("vault-001"))
    assert "streaming_output_equals_the_one_shot_reference" in rust


def test_a_changed_base_image_selects_every_task_of_its_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_diff(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout="images/go/Dockerfile\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_diff)
    assert validate_tasks.changed_task_ids("origin/main") == [
        "queue-001",
        "queue-002",
        "queue-003",
        "queue-004",
        "queue-005",
    ]


def test_a_changed_task_file_selects_that_task(monkeypatch: pytest.MonkeyPatch) -> None:
    changed = "task_bank/vault-001/hidden_tests/tests/hidden_1.rs\ndocs/design.md\n"

    def fake_diff(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout=changed, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_diff)
    assert validate_tasks.changed_task_ids("origin/main") == ["vault-001"]
