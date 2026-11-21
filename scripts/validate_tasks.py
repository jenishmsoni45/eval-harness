"""Task validation, Phase 1 subset (phases.md P1-2; task-spec.md V5 and V6).

For each task: build the base and task images, then in fresh containers, RUNS times each:

- shipped bug (V5): each bug test, run on its own, fails; the regression suite passes with
  exactly regression.count tests;
- reference fix (V6): the visible tests, each bug test and the regression suite all pass.

Every run must give the same results (D12). The full rule set V1-V13 arrives in Phase 2.

Each run is one `docker run --rm -i` with the sandbox's limits and no network. The hidden tests
and the patch enter only that container, as a tar archive on its standard input; nothing is
mounted, and nothing outlives the run.

Usage:
    python -m scripts.validate_tasks                        # every task in the bank
    python -m scripts.validate_tasks risk-001               # named tasks
    python -m scripts.validate_tasks --changed-since origin/main   # tasks a branch changed
"""

from __future__ import annotations

import argparse
import base64
import io
import shlex
import subprocess
import sys
import tarfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from harness.containers import leftover_containers, remove_containers
from harness.images import build_task_image
from harness.tasks import REPO_ROOT, TASK_BANK, Task, load_task, read_tree, task_ids
from harness.testrun import REPO_DIR, bug_test_command, regression_passed, regression_run

RUNS = 5
RUN_TIMEOUT_S = 600
OUTPUT_TAIL_BYTES = 20_000
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


@dataclass(frozen=True)
class RunResult:
    visible_exit: int
    bug_exits: dict[str, int]
    regression_ok: bool
    outputs: dict[str, str]

    def summary(self) -> tuple[bool, tuple[bool, ...], bool]:
        """What must be identical across runs: visible pass, each bug test's pass, regression."""
        return (
            self.visible_exit == 0,
            tuple(code == 0 for code in self.bug_exits.values()),
            self.regression_ok,
        )


def container_script(task: Task, with_patch: bool) -> str:
    """The shell script one validation run executes in its container."""
    steps = [("visible", task.visible_command)]
    steps += [(f"bug-{i}", bug_test_command(task, t)) for i, t in enumerate(task.bug_tests)]
    regression = regression_run(task)
    steps.append(("regression", regression.command))
    lines = [
        "set -u",
        "mkdir /tmp/evalh-in && tar -x -C /tmp/evalh-in || exit 97",
        f"cp -R /tmp/evalh-in/hidden/. {REPO_DIR}/ || exit 98",
        f"cd {REPO_DIR}",
    ]
    if with_patch:
        lines.append("git apply /tmp/evalh-in/fix.patch || exit 99")
    lines.append(
        'step() { name=$1; shift; "$@" >/tmp/evalh-out 2>&1; rc=$?; '
        f'printf \'@@evalh step %s %s %s\\n\' "$name" "$rc" '
        f'"$(tail -c {OUTPUT_TAIL_BYTES} /tmp/evalh-out | base64 -w0)"; }}'
    )
    lines += [f"step {name} {shlex.join(command)}" for name, command in steps]
    lines.append(
        f"[ -f {regression.report_path} ] && "
        f"printf '@@evalh report %s\\n' \"$(base64 -w0 {regression.report_path})\""
    )
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


def parse_output(task: Task, stdout: str) -> RunResult:
    exits: dict[str, int] = {}
    outputs: dict[str, str] = {}
    report: str | None = None
    for line in stdout.splitlines():
        parts = line.split(" ")
        if parts[:2] == ["@@evalh", "step"] and len(parts) in (4, 5):
            exits[parts[2]] = int(parts[3])
            outputs[parts[2]] = base64.b64decode(parts[4] if len(parts) == 5 else "").decode(
                errors="replace"
            )
        elif parts[:2] == ["@@evalh", "report"] and len(parts) == 3:
            report = base64.b64decode(parts[2]).decode(errors="replace")
    expected = {"visible", "regression", *(f"bug-{i}" for i in range(len(task.bug_tests)))}
    if set(exits) != expected:
        raise RuntimeError(f"validation run reported steps {sorted(exits)}, expected {expected}")
    return RunResult(
        visible_exit=exits["visible"],
        bug_exits={t: exits[f"bug-{i}"] for i, t in enumerate(task.bug_tests)},
        regression_ok=regression_passed(task, exits["regression"], report),
        outputs=outputs,
    )


def run_once(task: Task, image: str, patch: bytes | None) -> RunResult:
    """One validation run in a fresh container, removed when the run ends."""
    name = f"evalh-validate-{task.id}-{uuid.uuid4().hex[:8]}"
    command = [
        "docker", "run", "--rm", "--interactive", f"--name={name}", *SANDBOX_FLAGS,
        image, "sh", "-c", container_script(task, with_patch=patch is not None),
    ]  # fmt: skip
    try:
        result = subprocess.run(
            command,
            input=input_archive(task, patch),
            capture_output=True,
            timeout=RUN_TIMEOUT_S,
            check=False,
        )
    finally:
        # A killed client can leave the container running; make sure it is gone.
        remove_containers([n for n in leftover_containers() if n == name])
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(f"validation container exited {result.returncode}: {stderr[-2000:]}")
    return parse_output(task, result.stdout.decode(errors="replace"))


def shipped_problems(task: Task, run: RunResult) -> list[str]:
    problems = [
        f"bug test passed on the shipped bug: {t}" for t, c in run.bug_exits.items() if c == 0
    ]
    if not run.regression_ok:
        problems.append(
            f"regression suite did not pass with exactly {task.regression_count} tests on the "
            f"shipped bug:\n{run.outputs['regression']}"
        )
    return problems


def fixed_problems(task: Task, run: RunResult) -> list[str]:
    problems = []
    if run.visible_exit != 0:
        problems.append(f"visible tests failed with the reference fix:\n{run.outputs['visible']}")
    for i, (test, code) in enumerate(run.bug_exits.items()):
        if code != 0:
            problems.append(
                f"bug test failed with the reference fix: {test}\n{run.outputs[f'bug-{i}']}"
            )
    if not run.regression_ok:
        problems.append(
            f"regression suite did not pass with exactly {task.regression_count} tests with the "
            f"reference fix:\n{run.outputs['regression']}"
        )
    return problems


def validate(task: Task, runs: int = RUNS) -> list[str]:
    """Every problem found; an empty list means the task passed."""
    image = build_task_image(task)
    print(f"{task.id}: image {image}")
    patch = task.solution_patch.read_bytes()
    problems: list[str] = []
    for label, patch_or_none, judge in (
        ("shipped bug", None, shipped_problems),
        ("reference fix", patch, fixed_problems),
    ):
        results: list[RunResult] = []
        for i in range(1, runs + 1):
            try:
                run = run_once(task, image, patch_or_none)
            except RuntimeError as error:  # e.g. the patch does not apply
                problems.append(f"{label}, run {i}: {error}")
                continue
            results.append(run)
            problems += [f"{label}, run {i}: {p}" for p in judge(task, run)]
        if len({r.summary() for r in results}) > 1:
            problems.append(f"{label}: results differ between runs (flaky)")
        clean = sum(not judge(task, r) for r in results)
        n_bug = len(task.bug_tests)
        if label == "shipped bug":
            detail = f"each of the {n_bug} bug tests failed on its own; regression passed"
        else:
            detail = f"visible tests, all {n_bug} bug tests and regression passed"
        print(f"  {label:13} {clean}/{runs} runs: {detail} ({task.regression_count} tests)")
    print(f"  {'OK' if not problems else 'FAILED'}")
    return problems


def changed_task_ids(ref: str) -> list[str]:
    """Tasks whose files differ between ref and HEAD; every task if the canary changed."""
    diff = subprocess.run(
        ["git", "diff", "--name-only", f"{ref}...HEAD", "--", "task_bank/"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    ).stdout.split()
    if "task_bank/CANARY" in diff:
        return task_ids()
    changed = {Path(p).parts[1] for p in diff if len(Path(p).parts) > 2}
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
        problems = validate(load_task(task_id), runs=args.runs)
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
