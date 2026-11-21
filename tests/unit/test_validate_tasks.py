"""The Phase 1 validator (phases.md P1-2; task-spec.md V5, V6; D12): how it judges runs, and,
in Docker, that it accepts risk-001 and rejects a task whose fix does not fix the bug."""

from __future__ import annotations

import base64
import shutil
from pathlib import Path

import pytest

from harness.tasks import TASK_BANK, load_task
from scripts.validate_tasks import (
    RunResult,
    container_script,
    fixed_problems,
    parse_output,
    shipped_problems,
    validate,
)

TASK = load_task("risk-001")


def step_line(name: str, code: int, output: str = "") -> str:
    return f"@@evalh step {name} {code} {base64.b64encode(output.encode()).decode()}"


def report_with(n: int) -> str:
    xml = "<testsuites><testsuite>" + '<testcase name="t"/>' * n + "</testsuite></testsuites>"
    return f"@@evalh report {base64.b64encode(xml.encode()).decode()}"


def run(visible: int, bug: list[int], regression_exit: int, count: int) -> RunResult:
    lines = [step_line("visible", visible), step_line("regression", regression_exit, "log")]
    lines += [step_line(f"bug-{i}", code) for i, code in enumerate(bug)]
    lines.append(report_with(count))
    return parse_output(TASK, "\n".join(["noise", *lines, ""]))


def test_the_script_runs_every_bug_test_on_its_own_and_the_regression_suite() -> None:
    script = container_script(TASK, with_patch=True)
    for test in TASK.bug_tests:
        assert f"step bug-{TASK.bug_tests.index(test)} pytest -p no:cacheprovider {test}" in script
    assert "--junitxml=" in script
    assert "git apply /tmp/evalh-in/fix.patch" in script
    assert "git apply" not in container_script(TASK, with_patch=False)


def test_output_is_parsed_into_exit_codes_and_the_regression_verdict() -> None:
    result = run(0, [1, 1, 1], 0, TASK.regression_count)
    assert result.visible_exit == 0
    assert list(result.bug_exits.values()) == [1, 1, 1]
    assert result.regression_ok
    assert result.outputs["regression"] == "log"


def test_a_missing_step_is_an_error() -> None:
    with pytest.raises(RuntimeError, match="steps"):
        parse_output(TASK, step_line("visible", 0))


def test_the_shipped_bug_must_fail_each_bug_test_and_pass_regression() -> None:
    assert shipped_problems(TASK, run(1, [1, 1, 1], 0, TASK.regression_count)) == []
    assert len(shipped_problems(TASK, run(1, [1, 0, 1], 0, TASK.regression_count))) == 1
    assert len(shipped_problems(TASK, run(1, [1, 1, 1], 0, TASK.regression_count - 1))) == 1


def test_the_reference_fix_must_pass_everything() -> None:
    assert fixed_problems(TASK, run(0, [0, 0, 0], 0, TASK.regression_count)) == []
    assert len(fixed_problems(TASK, run(1, [0, 0, 0], 0, TASK.regression_count))) == 1
    assert len(fixed_problems(TASK, run(0, [0, 1, 0], 0, TASK.regression_count))) == 1
    assert len(fixed_problems(TASK, run(0, [0, 0, 0], 1, TASK.regression_count))) == 1


@pytest.mark.docker
def test_risk_001_validates(docker_engine: None) -> None:
    assert validate(TASK, runs=1) == []


@pytest.mark.docker
def test_a_fix_that_does_not_fix_is_rejected(docker_engine: None, tmp_path: Path) -> None:
    shutil.copytree(TASK_BANK / "risk-001", tmp_path / "risk-001")
    # Replace the reference fix with a patch that changes only a comment.
    patch = (tmp_path / "risk-001" / "solution.patch").read_text()
    fixed = "+    return t_ms - width_ms <= time_ms < t_ms\n"
    noop = patch.replace(fixed, "+    return t_ms - width_ms < time_ms < t_ms  # unchanged\n")
    assert noop != patch
    (tmp_path / "risk-001" / "solution.patch").write_text(noop)
    problems = validate(load_task("risk-001", bank=tmp_path), runs=1)
    assert any("bug test failed with the reference fix" in p for p in problems)
