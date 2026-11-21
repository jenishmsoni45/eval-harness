"""Running and reading tests per language (task-spec.md "Language specifics"): the commands, when
a bug test counts as passed, and how passed tests are counted."""

from __future__ import annotations

import json

import pytest

from harness.tasks import Task, load_task
from harness.testrun import (
    Run,
    bug_test_command,
    bug_test_passed,
    count_passed,
    regression_passed,
    regression_run,
    visible_run,
)

PY, GO, RUST = (load_task(t) for t in ("risk-001", "queue-001", "vault-001"))


def test_one_bug_test_runs_on_its_own_with_each_runner() -> None:
    assert bug_test_command(PY, "tests/hidden/t.py::test_a[x]") == (
        "pytest", "-p", "no:cacheprovider", "tests/hidden/t.py::test_a[x]",
    )  # fmt: skip
    assert bug_test_command(GO, "internal/scheduler:TestA") == (
        "go", "test", "-count=1", "-run", "^TestA$", "./internal/scheduler",
    )  # fmt: skip
    assert bug_test_command(RUST, "hidden_1:a_test") == (
        "cargo", "test", "--offline", "--test", "hidden_1", "--", "--exact", "a_test",
    )  # fmt: skip


def test_reports_come_from_a_junit_file_go_json_events_or_cargo_output() -> None:
    report = "/tmp/evalh-visible-report.xml"  # noqa: S108 (a path in the container)
    assert visible_run(PY) == Run((*PY.visible_command, f"--junitxml={report}"), report)
    assert regression_run(GO).command[:3] == ("go", "test", "-json")
    assert regression_run(GO).command[3:] == GO.regression_command[2:]
    assert regression_run(GO).report_path is None
    assert regression_run(RUST) == Run(RUST.regression_command, None)


@pytest.mark.parametrize(
    ("task", "exit_code", "output", "passed"),
    [
        (PY, 0, "1 passed", True),
        (PY, 1, "1 failed", False),
        (PY, 5, "no tests ran", False),  # nothing collected
        (GO, 0, "ok  \tgithub.com/x/internal/scheduler\t0.01s\n", True),
        (GO, 1, "--- FAIL: TestA\nFAIL\n", False),
        (GO, 0, "ok  \tgithub.com/x/internal/scheduler\t0.01s [no tests to run]\n", False),
        (GO, 0, "testing: warning: no tests to run\nPASS\n", False),
        (RUST, 0, "running 1 test\ntest a ... ok\n\ntest result: ok. 1 passed; 0 failed;", True),
        (RUST, 0, "running 0 tests\n\ntest result: ok. 0 passed; 0 failed; 0 ignored;", False),
        (RUST, 101, "test result: FAILED. 0 passed; 1 failed;", False),
    ],
)
def test_a_bug_test_passes_only_if_it_ran_and_passed(
    task: Task, exit_code: int, output: str, passed: bool
) -> None:
    assert bug_test_passed(task, exit_code, output) is passed


def go_events(*events: dict[str, str]) -> str:
    return "\n".join(json.dumps(e) for e in events)


def test_go_counts_pass_events_of_tests_and_subtests() -> None:
    report = "\n".join(
        [
            "# github.com/x/internal/scheduler [build output]",
            go_events(
                {"Action": "run", "Test": "TestA"},
                {"Action": "pass", "Test": "TestA"},
                {"Action": "pass", "Test": "TestB/sub"},
                {"Action": "pass", "Test": "TestB"},
                {"Action": "skip", "Test": "TestC"},
                {"Action": "fail", "Test": "TestD"},
                {"Action": "pass"},  # the package itself
            ),
        ]
    )
    assert count_passed(GO, report) == 3


def test_rust_adds_up_the_summary_of_every_test_target() -> None:
    output = (
        "     Running unittests src/lib.rs\n"
        "test result: ok. 23 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out\n"
        "     Running tests/invariants/main.rs\n"
        "test result: ok. 4 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out\n"
    )
    assert count_passed(RUST, output) == 27


def test_the_regression_run_needs_exit_0_and_the_exact_count() -> None:
    lines = [f"test result: ok. {RUST.regression_count} passed; 0 failed;"]
    assert regression_passed(RUST, 0, "\n".join(lines))
    assert not regression_passed(RUST, 101, "\n".join(lines))
    fewer = f"test result: ok. {RUST.regression_count - 1} passed; 0 failed; 1 ignored;"
    assert not regression_passed(RUST, 0, fewer)  # a test was skipped
    assert not regression_passed(GO, 0, None)
    assert not regression_passed(PY, 0, "<not xml")
