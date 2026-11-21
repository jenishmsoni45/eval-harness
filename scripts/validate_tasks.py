"""Task validation: rules V1-V10, V12 and V13 of task-spec.md "Validation rules" (E1, D12).

V11, the runner-detection check, arrives with the integrity checks in Phase 4. For each task:

- on the host: V1 (schema, id, canary, the task's files), V12 (canary in hidden material),
  V10 (protected paths), V9 (the reference fix's size), and V4 for the build context;
- the image: V2 (it builds from repo/ alone), V3 (one commit, no other .git) and V4 (no hidden
  material in `docker history` or anywhere in a container's filesystem);
- RUNS fresh containers for each of the shipped bug (V5), the reference fix (V6), the wrong
  patch (V7) and the partial patch (V8). Every run of one state must give the same results
  (D12). The shipped-bug runs also give V2 (the visible tests run offline) and V9 (visible
  results), and the reference-fix runs give V13 (time).

A run is one `docker run --rm -i` with the sandbox's limits and no network. It applies the patch,
runs the visible tests, and only then copies the hidden tests in (D40) and runs each bug test on
its own and the regression suite. The hidden tests and the patch enter only that container, as a
tar archive on its standard input; nothing is mounted, and nothing outlives the run.

Usage:
    python -m scripts.validate_tasks                        # every task in the bank
    python -m scripts.validate_tasks risk-001               # named tasks
    python -m scripts.validate_tasks --changed-since origin/main   # tasks a branch changed
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from harness.containers import leftover_containers, remove_containers
from harness.images import build_task_image
from harness.integrity import is_protected, protected_changes
from harness.tasks import (
    CANARY_FILE,
    REPO_ROOT,
    TASK_BANK,
    Task,
    TaskSpecError,
    canary,
    load_task,
    read_tree,
    task_ids,
)
from harness.testrun import (
    REPO_DIR,
    Run,
    bug_test_command,
    bug_test_passed,
    count_passed,
    regression_passed,
    regression_run,
    visible_run,
)

RUNS = 5
RUN_TIMEOUT_S = 900
SCORING_LIMIT_S = 300  # D21: the scoring phase's limit; V13 allows half of it
OUTPUT_TAIL_BYTES = 20_000
# The fewest characters a patch line needs before V4 looks for it in an image: shorter lines,
# such as `} else {`, occur everywhere.
MIN_PATTERN_LENGTH = 20
DIFFICULTY_LIMITS = {"easy": 5, "medium": 20}  # most changed lines in a one-file fix (task spec)
# The sandbox's settings (harness/sandbox/compose.yaml, D21), for a plain `docker run`.
SANDBOX_FLAGS = (
    "--network=none",
    "--user=agent",
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges:true",
    "--pids-limit=256",
    "--cpus=1",
    "--memory=2g",
    "--memory-swap=2g",
    "--init",
    "--env=TZ=UTC",
    "--env=LANG=C.UTF-8",
    "--env=PYTHONHASHSEED=0",
    f"--workdir={REPO_DIR}",
)
# The inspection container (V3, V4) reads every file in the image, so it runs as root with only
# the capability to read any file; everything else is as in the sandbox.
INSPECT_FLAGS = (
    *("--user=root" if flag == "--user=agent" else flag for flag in SANDBOX_FLAGS),
    "--cap-add=DAC_READ_SEARCH",
)

STATES = {
    # state: (rule, patch file or None)
    "shipped bug": ("V5", None),
    "reference fix": ("V6", "solution.patch"),
    "wrong patch": ("V7", "wrong.patch"),
    "partial patch": ("V8", "partial.patch"),
}


# --- One run in a fresh container ---------------------------------------------------------


@dataclass(frozen=True)
class RunResult:
    visible_exit: int
    visible_passed: int | None  # tests the visible run reports as passed; None if unreadable
    bug_passed: dict[str, bool]
    regression_ok: bool
    test_ms: int  # the test phase: visible run, bug tests and regression run
    outputs: dict[str, str]

    def summary(self) -> tuple[bool, tuple[bool, ...], bool]:
        """What must be identical across runs: visible pass, each bug test's pass, regression."""
        return (self.visible_exit == 0, tuple(self.bug_passed.values()), self.regression_ok)


def _report_lines(name: str, run: Run) -> list[str]:
    """Shell lines that print a run's report: its report file, or its whole output."""
    source = run.report_path or "/tmp/evalh-out"  # noqa: S108 (a path in the container)
    return [f'[ -f {source} ] && printf "@@evalh report {name} %s\\n" "$(base64 -w0 {source})"']


def container_script(task: Task, with_patch: bool) -> str:
    """The shell script one validation run executes in its container."""
    visible = visible_run(task)
    regression = regression_run(task)
    lines = [
        "set -u",
        "mkdir /tmp/evalh-in && tar -x -C /tmp/evalh-in || exit 97",
        f"cd {REPO_DIR}",
    ]
    if with_patch:
        lines.append("git apply /tmp/evalh-in/fix.patch || exit 99")
    lines.append(
        'step() { name=$1; shift; t0=$(date +%s%N); "$@" >/tmp/evalh-out 2>&1; rc=$?; '
        "t1=$(date +%s%N); "
        f'printf \'@@evalh step %s %s %s %s\\n\' "$name" "$rc" "$(( (t1 - t0) / 1000000 ))" '
        f'"$(tail -c {OUTPUT_TAIL_BYTES} /tmp/evalh-out | base64 -w0)"; }}'
    )
    # D40: the visible tests run before any hidden test is in the repo.
    lines.append(f"step visible {shlex.join(visible.command)}")
    lines += _report_lines("visible", visible)
    lines.append(f"cp -R /tmp/evalh-in/hidden/. {REPO_DIR}/ || exit 98")
    for i, test in enumerate(task.bug_tests):
        lines.append(f"step bug-{i} {shlex.join(bug_test_command(task, test))}")
    lines.append(f"step regression {shlex.join(regression.command)}")
    lines += _report_lines("regression", regression)
    lines.append("exit 0")
    return "\n".join(lines)


def input_archive(task: Task, patch: bytes | None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        entries = {f"hidden/{p}": data for p, data in read_tree(task.hidden_tests_dir).items()}
        if patch is not None:
            entries["fix.patch"] = patch
        for name, data in sorted(entries.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _decode(b64: str) -> str:
    return base64.b64decode(b64).decode(errors="replace")


def parse_output(task: Task, stdout: str) -> RunResult:
    exits: dict[str, int] = {}
    times: dict[str, int] = {}
    outputs: dict[str, str] = {}
    reports: dict[str, str] = {}
    for line in stdout.splitlines():
        parts = line.split(" ")
        if parts[:2] == ["@@evalh", "step"] and len(parts) in (5, 6):
            exits[parts[2]] = int(parts[3])
            times[parts[2]] = int(parts[4])
            outputs[parts[2]] = _decode(parts[5] if len(parts) == 6 else "")
        elif parts[:2] == ["@@evalh", "report"] and len(parts) in (3, 4):
            reports[parts[2]] = _decode(parts[3] if len(parts) == 4 else "")
    expected = {"visible", "regression", *(f"bug-{i}" for i in range(len(task.bug_tests)))}
    if set(exits) != expected:
        raise RuntimeError(f"validation run reported steps {sorted(exits)}, expected {expected}")
    try:
        visible_passed: int | None = count_passed(task, reports["visible"])
    except (KeyError, ValueError):  # no report, or one that does not parse
        visible_passed = None
    return RunResult(
        visible_exit=exits["visible"],
        visible_passed=visible_passed,
        bug_passed={
            t: bug_test_passed(task, exits[f"bug-{i}"], outputs[f"bug-{i}"])
            for i, t in enumerate(task.bug_tests)
        },
        regression_ok=regression_passed(task, exits["regression"], reports.get("regression")),
        test_ms=sum(times.values()),
        outputs=outputs,
    )


def _docker_run(name: str, flags: tuple[str, ...], image: str, script: str, stdin: bytes) -> str:
    """Run a script in a fresh container, removed when it ends; return its standard output."""
    command = ["docker", "run", "--rm", "--interactive", f"--name={name}", *flags, image,
               "sh", "-c", script]  # fmt: skip
    try:
        result = subprocess.run(
            command, input=stdin, capture_output=True, timeout=RUN_TIMEOUT_S, check=False
        )
    finally:
        # A killed client can leave the container running; make sure it is gone.
        remove_containers([n for n in leftover_containers() if n == name])
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(f"container exited {result.returncode}: {stderr[-2000:]}")
    return result.stdout.decode(errors="replace")


def run_once(task: Task, image: str, patch: bytes | None) -> RunResult:
    """One validation run in a fresh container, removed when the run ends."""
    name = f"evalh-validate-{task.id}-{uuid.uuid4().hex[:8]}"
    script = container_script(task, with_patch=patch is not None)
    stdout = _docker_run(name, SANDBOX_FLAGS, image, script, input_archive(task, patch))
    return parse_output(task, stdout)


# --- What each state must show -------------------------------------------------------------


def shipped_problems(task: Task, run: RunResult) -> list[str]:
    """V5: each bug test fails on its own; the regression suite passes with the exact count."""
    problems = [
        f"bug test passed on the shipped bug: {t}" for t, ok in run.bug_passed.items() if ok
    ]
    if not run.regression_ok:
        problems.append(
            f"regression suite did not pass with exactly {task.regression_count} tests on the "
            f"shipped bug:\n{run.outputs['regression']}"
        )
    return problems


def fixed_problems(task: Task, run: RunResult) -> list[str]:
    """V6: every visible, bug and regression test passes."""
    problems = []
    if run.visible_exit != 0:
        problems.append(f"visible tests failed with the reference fix:\n{run.outputs['visible']}")
    for i, (test, ok) in enumerate(run.bug_passed.items()):
        if not ok:
            problems.append(
                f"bug test failed with the reference fix: {test}\n{run.outputs[f'bug-{i}']}"
            )
    if not run.regression_ok:
        problems.append(
            f"regression suite did not pass with exactly {task.regression_count} tests with the "
            f"reference fix:\n{run.outputs['regression']}"
        )
    return problems


def wrong_problems(task: Task, run: RunResult) -> list[str]:
    """V7: visible and regression tests pass, and at least one bug test fails."""
    problems = []
    if run.visible_exit != 0:
        problems.append(f"visible tests failed with the wrong patch:\n{run.outputs['visible']}")
    if not run.regression_ok:
        problems.append(
            f"regression suite did not pass with the wrong patch:\n{run.outputs['regression']}"
        )
    if all(run.bug_passed.values()):
        problems.append("every bug test passed with the wrong patch")
    return problems


def partial_problems(task: Task, run: RunResult) -> list[str]:
    """V8: regression tests pass, and at least one but not all bug tests pass."""
    problems = []
    if not run.regression_ok:
        problems.append(
            f"regression suite did not pass with the partial patch:\n{run.outputs['regression']}"
        )
    passed = sum(run.bug_passed.values())
    if passed in (0, len(run.bug_passed)):
        problems.append(
            f"{passed} of {len(run.bug_passed)} bug tests passed with the partial patch; "
            "it must pass some but not all"
        )
    return problems


JUDGES: dict[str, Callable[[Task, RunResult], list[str]]] = {
    "shipped bug": shipped_problems,
    "reference fix": fixed_problems,
    "wrong patch": wrong_problems,
    "partial patch": partial_problems,
}


# --- Host-side rules -----------------------------------------------------------------------


REQUIRED_FILES = ("instructions.md", "Dockerfile", "solution.patch", "wrong.patch", "partial.patch")


def check_layout(path: Path) -> list[str]:
    """V1, for the task directory: every file the task spec lists is there."""
    problems = [f"missing {name}" for name in REQUIRED_FILES if not (path / name).is_file()]
    for directory in ("repo", "hidden_tests"):
        if not (path / directory).is_dir() or not any((path / directory).rglob("*")):
            problems.append(f"missing or empty {directory}/")
    return problems


def check_canary(task: Task) -> list[str]:
    """V12: every hidden-test file and patch carries the canary string."""
    marker = canary().encode()
    files = {f"hidden_tests/{p}": d for p, d in read_tree(task.hidden_tests_dir).items()}
    files |= {name: path.read_bytes() for name, path in task.patches.items()}
    return [f"{name} lacks the canary string" for name, data in files.items() if marker not in data]


@dataclass(frozen=True)
class PatchStats:
    files: tuple[str, ...]
    changed_lines: int


def patch_stats(patch: Path) -> PatchStats:
    """Files and changed lines (added plus removed) of a patch, from `git apply --numstat`."""
    result = subprocess.run(
        ["git", "apply", "--numstat", str(patch)],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    files, lines = [], 0
    for row in result.stdout.splitlines():
        added, removed, path = row.split("\t")
        files.append(path)
        lines += int(added) + int(removed)
    return PatchStats(tuple(files), lines)


def patched_files(task: Task, patch: Path) -> dict[str, bytes | None]:
    """The files a patch changes, with their content after `git apply` (None if deleted)."""
    with tempfile.TemporaryDirectory(prefix="evalh-patch-") as tmp:
        work = Path(tmp) / "repo"
        shutil.copytree(task.repo_dir, work)
        subprocess.run(
            ["git", "apply", str(patch.resolve())], cwd=work, check=True, capture_output=True
        )
        before, after = read_tree(task.repo_dir), read_tree(work)
    changed: dict[str, bytes | None] = {p: d for p, d in after.items() if before.get(p) != d}
    changed |= {p: None for p in before if p not in after}
    return changed


def check_protected(task: Task) -> list[str]:
    """V10: no patch touches a protected path; every hidden-test destination is protected."""
    problems = []
    pristine = read_tree(task.repo_dir)
    for name, path in task.patches.items():
        try:
            changed = patched_files(task, path)
        except subprocess.CalledProcessError as error:
            problems.append(f"{name} does not apply: {error.stderr.decode(errors='replace')}")
            continue
        for touched in protected_changes(task, pristine, changed):
            problems.append(f"{name} touches the protected path {touched}")
    for destination in read_tree(task.hidden_tests_dir):
        if not is_protected(task, destination):
            problems.append(f"hidden test {destination} is not inside a protected path")
    return problems


def check_difficulty_size(task: Task) -> list[str]:
    """V9, from the reference fix alone: its files and changed lines, and `hard_reason`."""
    stats = patch_stats(task.solution_patch)
    n = len(stats.files)
    if task.difficulty in DIFFICULTY_LIMITS:
        limit = DIFFICULTY_LIMITS[task.difficulty]
        if n != 1 or stats.changed_lines > limit:
            return [
                f"{task.difficulty} allows a fix of 1 file and at most {limit} changed lines; "
                f"solution.patch changes {n} file(s) and {stats.changed_lines} lines"
            ]
        return []
    if n < 2 and task.hard_reason is None:
        return ["a hard fix in one file needs a hard_reason"]
    return []


def leak_patterns(task: Task) -> list[str]:
    """What V4 looks for: the canary, each bug test's name, and each patch line that the shipped
    repo does not already contain (at least MIN_PATTERN_LENGTH characters)."""
    found = {canary()}
    for test in task.bug_tests:
        name = test.replace("::", ":").split(":")[-1].split("[")[0]
        found.add(name)
    pristine_lines = {
        line.strip()
        for data in read_tree(task.repo_dir).values()
        for line in data.decode(errors="replace").splitlines()
    }
    for path in task.patches.values():
        for line in path.read_text().splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                text = line[1:].strip()
                if len(text) >= MIN_PATTERN_LENGTH and text not in pristine_lines:
                    found.add(text)
    return sorted(found)


def find_patterns(texts: dict[str, str], patterns: list[str]) -> list[str]:
    return [
        f"{where} contains {p!r}" for where, text in texts.items() for p in patterns if p in text
    ]


def check_build_context(task: Task, patterns: list[str]) -> list[str]:
    """V4, for the build context: no file of repo/ contains hidden material, and none is a copy
    of a hidden-test file, a patch or task.yaml."""
    context = read_tree(task.repo_dir)
    secret_files = set(read_tree(task.hidden_tests_dir).values())
    secret_files |= {p.read_bytes() for p in [*task.patches.values(), task.path / "task.yaml"]}
    problems = find_patterns(
        {f"repo/{p}": d.decode(errors="replace") for p, d in context.items()}, patterns
    )
    problems += [
        f"repo/{p} is a copy of hidden material" for p, d in context.items() if d in secret_files
    ]
    return problems


# --- Image rules ---------------------------------------------------------------------------


def git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def expected_tree(task: Task) -> set[tuple[str, str, str]]:
    """(mode, blob id, path) for every file of the shipped snapshot, as `git ls-tree` lists it."""
    entries = set()
    for rel, data in read_tree(task.repo_dir).items():
        executable = (task.repo_dir / rel).stat().st_mode & 0o100
        entries.add(("100755" if executable else "100644", git_blob_id(data), rel))
    return entries


INSPECT_SCRIPT = """\
set -u
cd /work/repo
g() { git -c safe.directory='*' "$@"; }
printf '@@evalh commits %s\\n' "$(g cat-file --batch-all-objects --batch-check='%(objecttype)' \
  </dev/null | grep -c '^commit$')"
printf '@@evalh tree %s\\n' "$(g ls-tree -r -z --full-tree HEAD </dev/null | base64 -w0)"
printf '@@evalh gitdirs %s\\n' "$(find / -xdev \\( -path /proc -o -path /sys -o -path /dev \\) \
  -prune -o -name .git -print 2>/dev/null </dev/null | base64 -w0)"
roots=$(ls -d /* | grep -v -x -e /proc -e /sys -e /dev)
printf '@@evalh leaks %s\\n' "$(grep -r -l -F -f - $roots 2>/dev/null | base64 -w0)"
"""


def inspect_image(task: Task, image: str, patterns: list[str]) -> tuple[list[str], list[str]]:
    """V3 and V4 inside a container of the image: (V3 problems, V4 problems)."""
    name = f"evalh-inspect-{task.id}-{uuid.uuid4().hex[:8]}"
    stdout = _docker_run(name, INSPECT_FLAGS, image, INSPECT_SCRIPT, "\n".join(patterns).encode())
    fields = {}
    for line in stdout.splitlines():
        parts = line.split(" ")
        if parts[0] == "@@evalh" and len(parts) in (2, 3):
            fields[parts[1]] = parts[2] if len(parts) == 3 else ""
    v3: list[str] = []
    if fields.get("commits") != "1":
        v3.append(f"/work/repo/.git holds {fields.get('commits')} commits, not exactly 1")
    tree = set()
    for entry in filter(None, _decode(fields.get("tree", "")).split("\0")):
        meta, path = entry.split("\t", 1)
        mode, _, blob = meta.split(" ")
        tree.add((mode, blob, path))
    want = expected_tree(task)
    if tree != want:
        extra = sorted(p for _, _, p in tree - want)
        missing = sorted(p for _, _, p in want - tree)
        v3.append(f"the commit's tree differs from the snapshot: extra {extra}, missing {missing}")
    gitdirs = [
        d for d in _decode(fields.get("gitdirs", "")).splitlines() if d != f"{REPO_DIR}/.git"
    ]
    if gitdirs:
        v3.append(f"other .git directories: {gitdirs}")
    leaks = [p for p in _decode(fields.get("leaks", "")).splitlines() if p]
    v4 = [f"{path} in the image contains hidden material" for path in leaks]
    return v3, v4


def image_history(image: str) -> str:
    return subprocess.run(
        ["docker", "history", "--no-trunc", "--format", "{{.CreatedBy}}", image],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


# --- One task ------------------------------------------------------------------------------


@dataclass
class Findings:
    by_rule: dict[str, list[str]] = field(default_factory=dict)

    def add(self, rule: str, problems: list[str]) -> None:
        self.by_rule.setdefault(rule, []).extend(problems)

    def problems(self) -> list[str]:
        """Each problem once (repeated runs repeat them), prefixed with its rule, in rule order."""
        ordered = sorted(self.by_rule.items(), key=_rule_order)
        return list(dict.fromkeys(f"{rule}: {p}" for rule, ps in ordered for p in ps))


def _rule_order(item: tuple[str, list[str]]) -> int:
    return int(item[0][1:])


def run_state(task: Task, image: str, label: str, runs: int, findings: Findings) -> list[RunResult]:
    rule, patch_name = STATES[label]
    patch = (task.path / patch_name).read_bytes() if patch_name else None
    judge = JUDGES[label]
    results: list[RunResult] = []
    for i in range(1, runs + 1):
        try:
            result = run_once(task, image, patch)
        except RuntimeError as error:  # e.g. the patch does not apply
            findings.add(rule, [f"{label}, run {i}: {error}"])
            continue
        results.append(result)
        findings.add(rule, [f"{label}, run {i}: {p}" for p in judge(task, result)])
    if len({r.summary() for r in results}) > 1:
        findings.add(rule, [f"{label}: results differ between runs (flaky)"])
    clean = sum(not judge(task, r) for r in results)
    print(f"  {rule} {label:13} {clean}/{runs} runs as required")
    return results


def check_host(task_id: str, bank: Path = TASK_BANK) -> tuple[Task | None, Findings]:
    """The rules checked on the host, without Docker: V1, V12, V10, V9 (the reference fix's size
    and hard_reason) and V4 (the build context). Returns the task, or None if it cannot be
    loaded or is incomplete, and what was found."""
    findings = Findings()
    path = bank / task_id
    layout = check_layout(path)
    try:
        task = load_task(task_id, bank)
    except (TaskSpecError, FileNotFoundError) as error:
        findings.add("V1", [*layout, f"task.yaml: {error}"])
        return None, findings
    if task.canary != canary():
        findings.add("V1", [f"canary does not match {CANARY_FILE.relative_to(REPO_ROOT)}"])
    findings.add("V1", layout)
    if layout:
        return None, findings
    findings.add("V12", check_canary(task))
    findings.add("V10", check_protected(task))
    findings.add("V9", check_difficulty_size(task))
    findings.add("V4", check_build_context(task, leak_patterns(task)))
    return task, findings


def check_visible_results(task: Task, shipped: list[RunResult], findings: Findings) -> None:
    """V2 (the visible tests ran offline) and V9 (their result) from the shipped-bug runs."""
    for result in shipped:
        if not result.visible_passed:
            findings.add(
                "V2", ["the visible tests did not run on the shipped bug (no test passed)"]
            )
        fails = result.visible_exit != 0
        if task.difficulty == "easy" and not fails:
            findings.add("V9", ["an easy task needs a failing visible test on the shipped bug"])
        if task.difficulty != "easy" and fails:
            findings.add(
                "V9",
                [
                    f"a {task.difficulty} task's visible tests must all pass on the shipped bug:\n"
                    f"{result.outputs['visible']}"
                ],
            )


def validate(
    task_id: str,
    bank: Path = TASK_BANK,
    runs: int = RUNS,
    scoring_limit_s: float = SCORING_LIMIT_S,
) -> list[str]:
    """Every problem found, each prefixed with its rule; an empty list means the task is valid."""
    task, findings = check_host(task_id, bank)
    if task is None:
        print(f"{task_id}: FAILED (V1)")
        return findings.problems()
    try:
        image = build_task_image(task)
    except RuntimeError as error:
        findings.add("V2", [str(error)])
        print(f"{task_id}: FAILED (V2)")
        return findings.problems()
    print(f"{task_id}: image {image}")
    patterns = leak_patterns(task)
    v3, v4 = inspect_image(task, image, patterns)
    findings.add("V3", v3)
    findings.add("V4", v4)
    history = find_patterns({"docker history": image_history(image)}, patterns)
    findings.add("V4", history)

    results = {label: run_state(task, image, label, runs, findings) for label in STATES}
    check_visible_results(task, results["shipped bug"], findings)
    slowest = max((r.test_ms for r in results["reference fix"]), default=0)
    if slowest > scoring_limit_s * 1000 / 2:
        findings.add(
            "V13",
            [
                f"the scoring tests took {slowest / 1000:.1f} s with the reference fix, over "
                f"half the {scoring_limit_s:g} s scoring limit"
            ],
        )
    print(f"  V13 scoring tests with the reference fix: {slowest / 1000:.1f} s at most")

    problems = findings.problems()
    print(f"  {'OK' if not problems else 'FAILED'}")
    return problems


def changed_task_ids(ref: str) -> list[str]:
    """Tasks whose files differ between ref and HEAD; every task if the canary changed or a
    base image did."""
    diff = subprocess.run(
        ["git", "diff", "--name-only", f"{ref}...HEAD", "--", "task_bank/", "images/"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    ).stdout.split()
    if "task_bank/CANARY" in diff:
        return task_ids()
    changed_languages = {Path(p).parts[1] for p in diff if p.startswith("images/")}
    changed = {
        Path(p).parts[1] for p in diff if p.startswith("task_bank/") and len(Path(p).parts) > 2
    }
    for task_id in task_ids():
        try:
            if load_task(task_id).language in changed_languages:
                changed.add(task_id)
        except TaskSpecError:
            changed.add(task_id)  # validation reports it
    return sorted(i for i in changed if (TASK_BANK / i / "task.yaml").is_file())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("task_ids", nargs="*", help="tasks to validate (default: all)")
    parser.add_argument("--changed-since", metavar="REF", help="only tasks changed since REF")
    parser.add_argument("--runs", type=int, default=RUNS)
    args = parser.parse_args(argv)

    ids = args.task_ids or (
        changed_task_ids(args.changed_since) if args.changed_since else task_ids()
    )
    if not ids:
        print("no tasks to validate")
        return 0
    failed: dict[str, list[str]] = {}
    for task_id in ids:
        problems = validate(task_id, runs=args.runs)
        if problems:
            failed[task_id] = problems
    left = leftover_containers()
    if left:
        failed["containers"] = [f"left behind: {', '.join(left)}"]
    for task_id, problems in failed.items():
        print(f"\n{task_id}:", *problems, sep="\n  - ", file=sys.stderr)
    print(f"\n{len(ids) - len(failed.keys() - {'containers'})} of {len(ids)} tasks valid")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
