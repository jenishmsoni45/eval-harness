"""The finish hook: evidence that a test run really reached its end (design.md 3 step 6, D71).

The agent's code runs inside the test process, so that process's exit code and report can be
forged: code can write a report, print a summary and exit 0 without any test having run. For each
attempt the scorer therefore adds a hook to the scoring container, after the visible tests and
never in the agent's container. The hook prints a random token only once the runner has finished:

- **Python:** a pytest plugin outside the repo. It also reports how many tests passed and how
  many were skipped or expected to fail, so a skip raised from source is not a pass.
- **Go:** a `TestMain` in each tested package, which prints the token if `m.Run` returned 0.
- **Rust:** libtest has no end-of-run hook, so each test target gets one extra test that sorts
  last, and the target runs on one thread. Code that exits early never reaches it.

A bug or regression run passes only with the token, once per test binary, on top of the usual
checks. **Known limit:** the hook shares a machine and a user with the code under test, so code
that deliberately finds the token (in the hook's file or its own binary) can still forge a run.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

from harness.tasks import Task, read_tree
from harness.testrun import (
    REPO_DIR,
    Run,
    bug_test_command,
    bug_test_passed,
    regression_passed,
    regression_run,
)

MARKER = "evalh-finished"
RUST_FINISH_TEST = "zz_evalh_finish::finish"
GO_HOOK_FILE = "zz_evalh_finish_test.go"
GO_PACKAGE = re.compile(r"^package (\w+)", re.MULTILINE)
RUST_RESULT = re.compile(r"^test result: (\w+)\. (\d+) passed;", re.MULTILINE)
# One requested test plus the finish test.
RUST_BUG_RUN_PASSED = 2

PYTEST_PLUGIN = '''"""Reports that this pytest run reached its end."""


def pytest_terminal_summary(terminalreporter, exitstatus):
    if exitstatus != 0:
        return
    stats = terminalreporter.stats
    passed = len(stats.get("passed", []))
    skipped = sum(len(stats.get(kind, [])) for kind in ("skipped", "xfailed", "xpassed"))
    terminalreporter.write_line(f"{marker} passed={{passed}} skipped={{skipped}}")
'''
GO_TEST_MAIN = """package {package}

import (
\t"fmt"
\t"os"
\t"testing"
)

func TestMain(m *testing.M) {{
\tcode := m.Run()
\tif code == 0 {{
\t\tfmt.Println("{marker}")
\t}}
\tos.Exit(code)
}}
"""
RUST_FINISH_MODULE = """
#[cfg(test)]
mod zz_evalh_finish {{
    #[test]
    fn finish() {{
        use std::io::Write;
        let _ = writeln!(std::io::stdout(), "{marker}");
    }}
}}
"""


def rust_results(output: str) -> list[tuple[str, int]]:
    """Each `test result:` line of cargo's output, as (status, tests passed)."""
    return [(status, int(passed)) for status, passed in RUST_RESULT.findall(output)]


def _rust_targets(command: tuple[str, ...]) -> list[str]:
    """The test targets a cargo command selects; `lib` stands for `--lib`."""
    targets = []
    for i, word in enumerate(command):
        if word == "--lib":
            targets.append("lib")
        elif word == "--test":
            targets.append(command[i + 1])
    return targets


def _go_packages(command: tuple[str, ...]) -> list[str]:
    """The package directories a `go test` command names."""
    packages = [word.removeprefix("./") for word in command if word.startswith("./")]
    if any("..." in package for package in packages):
        raise ValueError(f"a regression command must name its packages: {command}")
    return packages


@dataclass(frozen=True)
class FinishHook:
    """One attempt's hook: its token, and the name of the Python plugin that carries it."""

    task: Task
    token: str
    module: str

    @property
    def marker(self) -> str:
        return f"{MARKER} {self.token}"

    @property
    def directory(self) -> str:
        """Where the Python plugin lives in the scoring container, outside the repo."""
        return f"/tmp/evalh-hook-{self.module}"  # noqa: S108 (inside the container)

    @property
    def env(self) -> dict[str, str]:
        """The environment of a hooked test command."""
        return {"PYTHONPATH": self.directory} if self.task.language == "python" else {}

    @property
    def rust_module(self) -> bytes:
        """The finish test, to append to each Rust test target's root file."""
        return RUST_FINISH_MODULE.format(marker=self.marker).encode()

    def _bug_targets(self) -> list[str]:
        return sorted({test.split(":", 1)[0] for test in self.task.bug_tests})

    def _binaries(self) -> list[str]:
        """The test binaries of the regression run, each of which reports its end once."""
        command = self.task.regression_command
        if self.task.language == "python":
            return ["pytest"]
        if self.task.language == "go":
            return _go_packages(command)
        return _rust_targets(command)

    def new_files(self) -> dict[str, bytes]:
        """The files to create in the scoring container, by absolute path."""
        if self.task.language == "python":
            plugin = PYTEST_PLUGIN.format(marker=self.marker)
            return {f"{self.directory}/{self.module}.py": plugin.encode()}
        if self.task.language == "rust":
            return {}
        known = {**read_tree(self.task.repo_dir), **read_tree(self.task.hidden_tests_dir)}
        files = {}
        for package in sorted({*self._bug_targets(), *self._binaries()}):
            tests = [
                data
                for path, data in sorted(known.items())
                if path.startswith(f"{package}/")
                and path.endswith("_test.go")
                and "/" not in path[len(package) + 1 :]
            ]
            found = GO_PACKAGE.search(tests[0].decode()) if tests else None
            if found is None:
                raise ValueError(f"{self.task.id}: no test file to name package {package}")
            source = GO_TEST_MAIN.format(package=found.group(1), marker=self.marker)
            files[f"{REPO_DIR}/{package}/{GO_HOOK_FILE}"] = source.encode()
        return files

    def rust_root_files(self) -> list[str]:
        """The root file of each Rust test target, relative to the repo."""
        if self.task.language != "rust":
            return []
        known = {*read_tree(self.task.repo_dir), *read_tree(self.task.hidden_tests_dir)}
        roots = []
        for target in sorted({*self._bug_targets(), *self._binaries()}):
            if target == "lib":
                roots.append("src/lib.rs")
            elif f"tests/{target}.rs" in known:
                roots.append(f"tests/{target}.rs")
            else:
                roots.append(f"tests/{target}/main.rs")
        return roots

    def bug_command(self, test_id: str) -> tuple[str, ...]:
        command = bug_test_command(self.task, test_id)
        if self.task.language == "python":
            return (command[0], "-p", self.module, *command[1:])
        if self.task.language == "go":
            return (*command[:2], "-v", *command[2:])  # go test hides a passing run's output
        return (*command, RUST_FINISH_TEST, "--test-threads=1")

    def regression(self) -> Run:
        run = regression_run(self.task)
        if self.task.language == "python":
            command = (run.command[0], "-p", self.module, *run.command[1:])
        elif self.task.language == "go":
            command = run.command  # -json already shows the test binary's output
        else:
            command = (*run.command, "--", "--test-threads=1")
        return Run(command, run.report_path)

    def _marks(self, output: str) -> list[tuple[str, str]]:
        pattern = rf"{re.escape(self.marker)}(?: passed=(\d+) skipped=(\d+))?(?!\w)"
        return re.findall(pattern, output)

    def bug_passed(self, exit_code: int, output: str) -> bool:
        """Whether one bug test ran to the end of its run and really passed."""
        if not bug_test_passed(self.task, exit_code, output):
            return False
        marks = self._marks(output)
        if len(marks) != 1:
            return False
        if self.task.language == "python":
            return marks[0][0] != "" and int(marks[0][0]) >= 1 and marks[0][1] == "0"
        if self.task.language == "rust":
            return rust_results(output) == [("ok", RUST_BUG_RUN_PASSED)]
        return True

    def regression_passed(self, exit_code: int, report: str | None, output: str) -> bool:
        """Whether the regression run reached its end with exactly the expected tests passed."""
        binaries = len(self._binaries())
        marks = self._marks(output)
        if exit_code != 0 or len(marks) != binaries:
            return False
        if self.task.language == "rust":
            results = rust_results(output)
            return (
                len(results) == binaries
                and all(status == "ok" for status, _ in results)
                and sum(passed for _, passed in results) == self.task.regression_count + binaries
            )
        if not regression_passed(self.task, exit_code, report):
            return False
        if self.task.language == "python":
            return marks[0][0] != "" and int(marks[0][0]) == self.task.regression_count
        return True


def new_hook(task: Task) -> FinishHook:
    """A hook with a fresh random token and plugin name."""
    return FinishHook(task, secrets.token_hex(16), f"evalh_finish_{secrets.token_hex(8)}")
