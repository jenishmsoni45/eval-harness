"""The minimal Phase 1 scorer (design.md 3, D10, D11).

After the agent submits, the scorer:

1. reads the agent's /work/repo out of the `default` container as a tar archive;
2. compares it with the pristine snapshot on the host (task_bank/<id>/repo/): files added,
   changed and deleted;
3. writes those changes into the idle `scorer` container, a fresh container from the same image,
   then copies the hidden tests in;
4. runs each bug test on its own, then the regression suite, and computes `base` (D11).

It uses only Inspect's sandbox interface (exec, read_file, write_file), so the RL environment can
call the same code later. Dropping protected changes, the integrity checks, the reward with cheat
flags and the scoring limit arrive in Phases 3 and 4. A Docker error is raised, not scored, so
Inspect retries the attempt (design.md 8).
"""

from __future__ import annotations

import io
import posixpath
import tarfile
import uuid
from dataclasses import dataclass, field

from inspect_ai.scorer import Score, Scorer, Target, mean, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import SandboxEnvironment, sandbox

from harness.tasks import IGNORED_DIRS, IGNORED_SUFFIXES, Task, is_ignored, load_task, read_tree
from harness.testrun import (
    REPO_DIR,
    base_reward,
    bug_test_command,
    bug_test_passed,
    regression_passed,
    regression_run,
)

# Phase 1 bound on each test command; the 5-minute scoring limit itself arrives in Phase 3.
COMMAND_TIMEOUT_S = 300
# tar --exclude patterns for the ignored paths of task-spec.md, matched at any depth.
TAR_EXCLUDES = tuple(
    f"--exclude={pattern}"
    for pattern in [*sorted(IGNORED_DIRS), *(f"*{suffix}" for suffix in IGNORED_SUFFIXES)]
)


@dataclass(frozen=True)
class Changes:
    """The agent's changes to regular, non-ignored files, relative to the repo root."""

    written: dict[str, bytes] = field(default_factory=dict)  # added or changed
    deleted: tuple[str, ...] = ()

    @property
    def paths(self) -> list[str]:
        return sorted([*self.written, *self.deleted])


def files_from_tar(archive: bytes) -> dict[str, bytes]:
    """Regular, non-ignored files of a tar archive of the repo, keyed by relative path. Links and
    special files are never scored (design.md 3 step 3)."""
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar:
            rel = posixpath.normpath(member.name)
            if not member.isfile() or rel.startswith("..") or rel.startswith("/"):
                continue
            if is_ignored(rel):
                continue
            extracted = tar.extractfile(member)
            if extracted is not None:
                files[rel] = extracted.read()
    return files


def diff_trees(pristine: dict[str, bytes], current: dict[str, bytes]) -> Changes:
    written = {path: data for path, data in current.items() if pristine.get(path) != data}
    deleted = tuple(sorted(path for path in pristine if path not in current))
    return Changes(written=dict(sorted(written.items())), deleted=deleted)


async def read_repo(box: SandboxEnvironment) -> dict[str, bytes]:
    """Stream /work/repo out of a container as a tar archive, skipping ignored paths."""
    archive = f"/tmp/evalh-repo-{uuid.uuid4().hex}.tar"  # noqa: S108 (inside the container)
    result = await box.exec(
        ["tar", "--create", "--file", archive, *TAR_EXCLUDES, "--directory", REPO_DIR, "."],
        timeout=COMMAND_TIMEOUT_S,
    )
    if not result.success:
        raise RuntimeError(f"could not archive the agent's repo: {result.stderr}")
    try:
        data = await box.read_file(archive, text=False)
    finally:
        await box.exec(["rm", "-f", archive], timeout=COMMAND_TIMEOUT_S)
    return files_from_tar(data)


async def apply_changes(box: SandboxEnvironment, changes: Changes) -> None:
    for path, data in changes.written.items():
        await box.write_file(f"{REPO_DIR}/{path}", data)
    if changes.deleted:
        paths = [f"{REPO_DIR}/{path}" for path in changes.deleted]
        result = await box.exec(["rm", "-f", "--", *paths], timeout=COMMAND_TIMEOUT_S)
        if not result.success:
            raise RuntimeError(f"could not delete files in the scorer: {result.stderr}")


async def copy_hidden_tests(box: SandboxEnvironment, task: Task) -> None:
    """Copy hidden_tests/ to its destination paths inside the repo, only now, only here."""
    for path, data in read_tree(task.hidden_tests_dir).items():
        await box.write_file(f"{REPO_DIR}/{path}", data)


async def run_bug_test(box: SandboxEnvironment, task: Task, test_id: str) -> bool:
    """Whether one bug test, run on its own, passes. A command that hangs past its bound counts
    as failed: that is the agent's outcome, not an infrastructure failure (design.md 3 step 6)."""
    command = bug_test_command(task, test_id)
    try:
        result = await box.exec(list(command), cwd=REPO_DIR, timeout=COMMAND_TIMEOUT_S)
    except TimeoutError:
        return False
    return bug_test_passed(task, result.returncode, result.stdout + result.stderr)


async def run_regression(box: SandboxEnvironment, task: Task) -> bool:
    regression = regression_run(task)
    try:
        result = await box.exec(list(regression.command), cwd=REPO_DIR, timeout=COMMAND_TIMEOUT_S)
    except TimeoutError:
        return False
    report: str | None
    if regression.report_path is None:  # the runner's own output is the report
        report = result.stdout + result.stderr
    else:
        try:
            report = await box.read_file(regression.report_path)
        except FileNotFoundError:
            report = None
    return regression_passed(task, result.returncode, report)


async def score_attempt(
    agent_box: SandboxEnvironment, scorer_box: SandboxEnvironment, task: Task
) -> Score:
    changes = diff_trees(read_tree(task.repo_dir), await read_repo(agent_box))
    await apply_changes(scorer_box, changes)
    await copy_hidden_tests(scorer_box, task)
    bug_results = {t: await run_bug_test(scorer_box, task, t) for t in task.bug_tests}
    regression_ok = await run_regression(scorer_box, task)
    base = base_reward(list(bug_results.values()), regression_ok)
    return Score(
        value=base,
        explanation=(
            f"{sum(bug_results.values())} of {len(bug_results)} bug tests passed; "
            f"regression suite {'passed' if regression_ok else 'failed'}"
        ),
        metadata={
            "base": base,
            "bug_tests": bug_results,
            "regression_passed": regression_ok,
            "changed_files": changes.paths,
        },
    )


@scorer(metrics=[mean()])
def hidden_tests() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        task = load_task(str(state.metadata["task_id"]))
        return await score_attempt(sandbox("default"), sandbox("scorer"), task)

    return score
