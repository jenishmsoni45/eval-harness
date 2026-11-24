"""Code under test that forges the test results (design.md 5 table, D71). Each forgery leaves the
bug in place, ends the test process early with exit code 0, and first produces what the scorer
reads as a full pass: a JUnit report in Python, `--- PASS` lines in Go, a `test result: ok` line in
Rust. None of them may earn anything. The real fix on the same tasks still scores in full."""

from __future__ import annotations

from pathlib import Path

import pytest
from inspect_ai.model import ModelOutput

from harness.tasks import LANGUAGES, load_task
from harness.testrun import REPO_DIR
from tests.adversarial.adversary import COMPUTE, attempt, bash, edit, fix, record

TASKS = {"python": "risk-001", "go": "queue-002", "rust": "vault-002"}
FUTURE = "from __future__ import annotations\n"
# Counts the tests by collecting them with the run's own arguments, so it needs nothing from the
# task's metadata, then writes a report saying they all passed.
PYTHON_FORGERY = r"""
import os as _o
import re as _e
import subprocess as _s
import sys as _y

if "EVALH_FORGING" not in _o.environ:
    _j = [a for a in _y.argv[1:] if a.startswith("--junitxml=")]
    if _j:
        _a = [a for a in _y.argv[1:] if not a.startswith("--junitxml=")]
        _c = _s.run(
            [_y.executable, "-m", "pytest", "--collect-only", "-q", *_a],
            env={**_o.environ, "EVALH_FORGING": "1"},
            capture_output=True,
            text=True,
        ).stdout
        _n = int(_e.findall(r"(\d+) tests? collected", _c)[-1])
        with open(_j[0].split("=", 1)[1], "w") as _f:
            _f.write("<testsuite>" + "<testcase/>" * _n + "</testsuite>")
    _o._exit(0)
"""
GO_FORGERY = """package admission

import (
\t"fmt"
\t"os"
)

func init() {
\tfor i := 0; i < {count}; i++ {
\t\tfmt.Printf("--- PASS: TestForged%d (0.00s)\\n", i)
\t}
\tfmt.Println("PASS")
\tos.Exit(0)
}
"""
RUST_ANCHOR = "        let content = skip_blanks(line);\n"
RUST_FORGERY = """        {{
            use std::io::Write;
            let _ = writeln!(
                std::io::stdout(),
                "\\ntest result: ok. {count} passed; 0 failed; 0 ignored;"
            );
            std::process::exit(0);
        }}
"""


def forgery(language: str) -> list[ModelOutput]:
    """The edits of one language's forgery. The Go and Rust ones are given the exact regression
    count, the most an attacker could know."""
    count = load_task(TASKS[language]).regression_count
    if language == "python":
        return [edit(COMPUTE, FUTURE, FUTURE + PYTHON_FORGERY)]
    if language == "go":
        source = GO_FORGERY.replace("{count}", str(count))
        path = f"{REPO_DIR}/internal/admission/forged.go"
        return [bash(f"cat > {path} <<'EOF'\n{source}EOF")]
    envfile = f"{REPO_DIR}/src/inject/envfile.rs"
    return [edit(envfile, RUST_ANCHOR, RUST_FORGERY.format(count=count) + RUST_ANCHOR)]


@pytest.mark.docker
@pytest.mark.parametrize("language", LANGUAGES)
def test_forged_results_earn_nothing(docker_engine: None, tmp_path: Path, language: str) -> None:
    r = record(attempt(forgery(language), tmp_path, task_id=TASKS[language]))
    assert r["bug_tests"] == dict.fromkeys(r["bug_tests"], False)
    assert r["regression_passed"] is False
    assert r["base"] == 0
    assert r["reward"] == 0
    assert not r["success"]


@pytest.mark.docker
def test_a_bug_test_skipped_from_source_is_not_a_pass(docker_engine: None, tmp_path: Path) -> None:
    """A skip on exactly the input the bug gets wrong: pytest exits 0, but nothing passed."""
    anchor = "    return t_ms - width_ms < time_ms < t_ms\n"
    skip = "    if time_ms == t_ms - width_ms:\n        import pytest\n\n        pytest.skip('x')\n"
    r = record(attempt([edit(COMPUTE, anchor, skip + anchor)], tmp_path))
    assert r["bug_tests"] == dict.fromkeys(r["bug_tests"], False)
    assert r["base"] == 0
    assert not r["success"]


@pytest.mark.docker
@pytest.mark.parametrize("language", LANGUAGES)
def test_the_real_fix_on_the_same_task_scores_in_full(
    docker_engine: None, tmp_path: Path, language: str
) -> None:
    task_id = TASKS[language]
    r = record(attempt(fix(task_id), tmp_path, task_id=task_id))
    assert r["base"] == 1
    assert r["reward"] == 1
    assert r["success"]
