"""How tests are run and read, per language (task-spec.md "Language specifics").

The validator and the scorer both build their commands and read their results here, so a task
is judged the same way at validation and at scoring. Phase 1 covers Python; Go and Rust arrive
with their images in Phase 2.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET  # parses a report the harness's own pytest run wrote
from dataclasses import dataclass

from harness.tasks import Task

REPO_DIR = "/work/repo"
# Where the regression run writes its report, inside the scoring or validation container.
REPORT_PATH = "/tmp/evalh-regression-report.xml"  # noqa: S108 (a fixed path in a container)


@dataclass(frozen=True)
class Regression:
    command: tuple[str, ...]
    report_path: str


def _require_python(task: Task) -> None:
    if task.language != "python":
        raise NotImplementedError(f"{task.language} test running arrives in Phase 2")


def bug_test_command(task: Task, test_id: str) -> tuple[str, ...]:
    """The command that runs one bug test on its own. Exit code 0 is a pass; anything else,
    including pytest's exit code 5 (nothing collected), is a fail."""
    _require_python(task)
    return ("pytest", "-p", "no:cacheprovider", test_id)


def regression_run(task: Task) -> Regression:
    """The regression command, with a machine-readable report of what ran."""
    _require_python(task)
    return Regression((*task.regression_command, f"--junitxml={REPORT_PATH}"), REPORT_PATH)


def count_passed(task: Task, report: str) -> int:
    """The number of tests the runner reports as run and passed: for pytest, the test cases in
    the JUnit report with no failure, error or skipped element."""
    _require_python(task)
    # The report comes from the harness's own pytest run. The agent's code runs in that process
    # too; hardening the scorer against tampering is Phase 4's adversarial work.
    root = ET.fromstring(report)  # noqa: S314
    return sum(
        1
        for case in root.iter("testcase")
        if not any(child.tag in ("failure", "error", "skipped") for child in case)
    )


def regression_passed(task: Task, exit_code: int, report: str | None) -> bool:
    """design.md 3 step 6: the regression run passes only if it exits 0 and the runner reports
    exactly regression.count tests run and passed (this catches skipped tests)."""
    if exit_code != 0 or report is None:
        return False
    try:
        return count_passed(task, report) == task.regression_count
    except ET.ParseError:
        return False


def base_reward(bug_passed: list[bool], regression_ok: bool) -> float:
    """D11: the share of bug tests passing if every regression test passes, else 0."""
    if not bug_passed:
        raise ValueError("a task has at least one bug test")
    return sum(bug_passed) / len(bug_passed) if regression_ok else 0.0
