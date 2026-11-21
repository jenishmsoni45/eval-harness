"""How tests are run and read, per language (task-spec.md "Language specifics").

The validator and the scorer both build their commands and read their results here, so a task
is judged the same way at validation and at scoring.

- One bug test: `pytest -p no:cacheprovider <node id>`; `go test -count=1 -run '^<Name>$'
  ./<package>`; `cargo test --offline --test <target> -- --exact <name>`.
- A bug test passes on exit code 0, and only if it ran: pytest's exit code 5 (nothing collected)
  is non-zero; for Go the output must not say "no tests to run"; for Rust at least one test must
  have passed.
- Tests passed are counted from pytest's `--junitxml` report, `go test -json` pass events, and
  cargo's `test result:` summary lines.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET  # parses a report the harness's own pytest run wrote
from dataclasses import dataclass

from harness.tasks import Task

REPO_DIR = "/work/repo"
# Where a Python run writes its JUnit report, inside the scoring or validation container.
REPORT_PATH = "/tmp/evalh-{name}-report.xml"  # noqa: S108 (a fixed path in a container)

GO_NO_TESTS = ("[no tests to run]", "testing: warning: no tests to run")
RUST_SUMMARY = re.compile(r"^test result: \w+\. (\d+) passed;", re.MULTILINE)


@dataclass(frozen=True)
class Run:
    """A test command with a machine-readable report of what passed: a file the runner writes at
    `report_path`, or, when that is None, the command's own output (stdout and stderr)."""

    command: tuple[str, ...]
    report_path: str | None


def bug_test_command(task: Task, test_id: str) -> tuple[str, ...]:
    """The command that runs one bug test on its own."""
    if task.language == "python":
        return ("pytest", "-p", "no:cacheprovider", test_id)
    if task.language == "go":
        package, name = test_id.rsplit(":", 1)
        return ("go", "test", "-count=1", "-run", f"^{name}$", f"./{package}")
    target, name = test_id.split(":", 1)
    return ("cargo", "test", "--offline", "--test", target, "--", "--exact", name)


def bug_test_passed(task: Task, exit_code: int, output: str) -> bool:
    """Whether one bug test ran and passed. A run that selects no test is a fail, whatever its
    exit code (task-spec.md "Language specifics")."""
    if exit_code != 0:
        return False
    if task.language == "go":
        return not any(marker in output for marker in GO_NO_TESTS)
    if task.language == "rust":
        return _rust_passed(output) >= 1
    return True


def reported_run(task: Task, command: tuple[str, ...], name: str) -> Run:
    """`command` with the option that makes the runner report each test: a JUnit file for
    pytest, JSON events for `go test`; cargo's summary lines need no option."""
    if task.language == "python":
        path = REPORT_PATH.format(name=name)
        return Run((*command, f"--junitxml={path}"), path)
    if task.language == "go":
        if command[:2] != ("go", "test"):
            raise ValueError(f"{task.id}: a Go test command starts with `go test`: {command}")
        return Run(("go", "test", "-json", *command[2:]), None)
    if command[:2] != ("cargo", "test"):
        raise ValueError(f"{task.id}: a Rust test command starts with `cargo test`: {command}")
    return Run(command, None)


def regression_run(task: Task) -> Run:
    return reported_run(task, task.regression_command, "regression")


def visible_run(task: Task) -> Run:
    return reported_run(task, task.visible_command, "visible")


def _rust_passed(output: str) -> int:
    return sum(int(n) for n in RUST_SUMMARY.findall(output))


def count_passed(task: Task, report: str) -> int:
    """The number of tests the runner reports as run and passed.

    - pytest: test cases in the JUnit report with no failure, error or skipped element;
    - Go: `pass` events of a test or subtest (events without a test are the package's own);
    - Rust: the sum of `N passed` over the `test result:` lines, one per test target.

    The report comes from the harness's own run, but the agent's code runs in that process too;
    hardening against a forged report is Phase 4's adversarial work.
    """
    if task.language == "python":
        root = ET.fromstring(report)  # noqa: S314
        return sum(
            1
            for case in root.iter("testcase")
            if not any(child.tag in ("failure", "error", "skipped") for child in case)
        )
    if task.language == "go":
        passed = 0
        for line in report.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue  # build output and other text between the events
            if isinstance(event, dict) and event.get("Action") == "pass" and event.get("Test"):
                passed += 1
        return passed
    return _rust_passed(report)


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
