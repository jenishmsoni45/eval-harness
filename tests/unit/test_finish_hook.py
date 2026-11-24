"""The finish hook's commands and verdicts (design.md 3 step 6, D71). The forged runs themselves
are played against the real scorer in tests/adversarial/test_forged_results.py."""

from __future__ import annotations

import pytest

from harness.finish_hook import GO_HOOK_FILE, RUST_FINISH_TEST, FinishHook, new_hook
from harness.tasks import load_task
from harness.testrun import REPO_DIR

PYTHON, GO, RUST, RUST_TARGETS = "risk-001", "queue-002", "vault-002", "vault-004"


def hook(task_id: str) -> FinishHook:
    return new_hook(load_task(task_id))


def junit(count: int) -> str:
    return "<testsuites><testsuite>" + '<testcase name="t"/>' * count + "</testsuite></testsuites>"


def test_every_hook_has_its_own_token_and_plugin_name() -> None:
    first, second = hook(PYTHON), hook(PYTHON)
    assert first.token != second.token
    assert first.module != second.module


def test_the_python_plugin_lives_outside_the_repo() -> None:
    h = hook(PYTHON)
    [path] = h.new_files()
    assert not path.startswith(REPO_DIR)
    assert h.env == {"PYTHONPATH": h.directory}
    assert h.bug_command(h.task.bug_tests[0])[:3] == ("pytest", "-p", h.module)
    assert h.regression().command[:3] == ("pytest", "-p", h.module)


@pytest.mark.parametrize("mark", ["", "passed=0 skipped=0", "passed=1 skipped=1"])
def test_a_python_bug_run_without_a_real_pass_fails(mark: str) -> None:
    h = hook(PYTHON)
    assert not h.bug_passed(0, f"{h.marker} {mark}".strip())


def test_a_python_bug_run_needs_the_token() -> None:
    h = hook(PYTHON)
    assert h.bug_passed(0, f"{h.marker} passed=1 skipped=0")
    assert not h.bug_passed(1, f"{h.marker} passed=1 skipped=0")
    assert not h.bug_passed(0, "1 passed")
    assert not h.bug_passed(0, "evalh-finished wrongtoken passed=1 skipped=0")


def test_a_python_regression_run_needs_the_token_and_the_exact_count() -> None:
    h = hook(PYTHON)
    count = h.task.regression_count
    good = f"{h.marker} passed={count} skipped=0"
    assert h.regression_passed(0, junit(count), good)
    assert not h.regression_passed(0, junit(count), "forged, no token")
    assert not h.regression_passed(0, junit(count), f"{h.marker} passed={count - 1} skipped=1")
    assert not h.regression_passed(0, junit(count - 1), good)
    assert not h.regression_passed(1, junit(count), good)


def test_go_adds_a_test_main_to_the_tested_package() -> None:
    h = hook(GO)
    [(path, source)] = h.new_files().items()
    assert path == f"{REPO_DIR}/internal/admission/{GO_HOOK_FILE}"
    assert source.startswith(b"package admission")
    assert h.marker.encode() in source
    assert h.bug_command(h.task.bug_tests[0])[:3] == ("go", "test", "-v")


def test_a_go_run_needs_the_token() -> None:
    h = hook(GO)
    assert h.bug_passed(0, f"--- PASS: TestX\nPASS\n{h.marker}\nok")
    assert not h.bug_passed(0, "--- PASS: TestX\nPASS\nok")
    assert not h.bug_passed(0, f"{h.marker}\nok [no tests to run]")
    count = h.task.regression_count
    events = '{"Action":"pass","Test":"T"}\n' * count
    assert h.regression_passed(0, events, events + h.marker)
    assert not h.regression_passed(0, events, events)


def test_rust_adds_the_finish_test_to_every_target() -> None:
    h = hook(RUST_TARGETS)
    assert h.new_files() == {}
    assert sorted(h.rust_root_files()) == [
        "src/lib.rs",
        "tests/hidden_1.rs",
        "tests/hidden_2.rs",
        "tests/invariants/main.rs",
    ]
    assert h.marker.encode() in h.rust_module
    command = h.bug_command(h.task.bug_tests[0])
    assert command[-2:] == (RUST_FINISH_TEST, "--test-threads=1")
    assert h.regression().command[-2:] == ("--", "--test-threads=1")


def rust_output(*results: tuple[str, int]) -> str:
    return "".join(f"test result: {s}. {n} passed; 0 failed;\n" for s, n in results)


def test_a_rust_bug_run_needs_the_requested_test_and_the_finish_test() -> None:
    h = hook(RUST)
    assert h.bug_passed(0, h.marker + "\n" + rust_output(("ok", 2)))
    # Only the finish test ran: the requested test does not exist.
    assert not h.bug_passed(0, h.marker + "\n" + rust_output(("ok", 1)))
    assert not h.bug_passed(0, h.marker + "\n" + rust_output(("FAILED", 2)))
    assert not h.bug_passed(0, rust_output(("ok", 2)))


def test_a_rust_regression_run_needs_a_token_from_every_target() -> None:
    h = hook(RUST_TARGETS)
    count = h.task.regression_count
    results = (("ok", count - 1), ("ok", 2), ("ok", 2))
    marks = (h.marker + "\n") * 3
    assert h.regression_passed(0, None, marks + rust_output(*results))
    assert not h.regression_passed(0, None, (h.marker + "\n") * 2 + rust_output(*results))
    assert not h.regression_passed(0, None, marks + rust_output(("ok", count - 1), ("ok", 2)))
    failed = (("FAILED", count - 1), ("ok", 2), ("ok", 2))
    assert not h.regression_passed(0, None, marks + rust_output(*failed))
    assert not h.regression_passed(1, None, marks + rust_output(*results))
