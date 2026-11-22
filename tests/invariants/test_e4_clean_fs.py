"""E4 (design.md 1, phases.md P3-3): every attempt starts with /work/repo identical to the shipped
snapshot and with no file left by an earlier attempt anywhere writable.

A marker agent makes two consecutive attempts at each task (one sample at a time). Each attempt:

1. checks: every writable file holding the run's token, every marker file anywhere, the number of
   commits in the repository, and a hash of the repo's files (the ignored paths left out);
2. leaves the token in marker files in /work/repo, /tmp, /var/tmp, /dev/shm and $HOME, appends it
   to a tracked file and commits;
3. checks again, which shows the check sees what was left;
4. submits.

The first check of every attempt, the second attempt's above all, must find nothing, one commit,
and the hash of the pristine snapshot as computed on the host. E4 across a retry is Phase 5's
E6 test. Run on one task per language (D15).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from inspect_ai import task_with
from inspect_ai.model import Model, ModelOutput
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer
from inspect_ai.solver import TaskState

from harness.agents.scripted import Turn, scripted_model, submit, tool_call
from harness.eval import evalh, run_eval
from harness.tasks import IGNORED_DIRS, IGNORED_SUFFIXES, load_task, read_tree
from tests.runs import bash_outputs, one_task_per_language, samples

MODEL = "mockllm/marker"
MARKER = "evalh-e4-marker"
PLACES = ("/work/repo", "/tmp", "/var/tmp", "/dev/shm", '"$HOME"')  # noqa: S108 (in the sandbox)

PRUNE = " -o ".join(f"-name {d}" for d in sorted(IGNORED_DIRS))
SKIP = " ".join(f"! -name '*{s}'" for s in IGNORED_SUFFIXES)
TREE_HASH = (
    f"cd /work/repo && find . \\( {PRUNE} \\) -prune -o -type f {SKIP} -print0 "
    "| LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1"
)


def check(token: str) -> str:
    return "; ".join(
        [
            "find / \\( -path /proc -o -path /sys \\) -prune -o -type f -writable -print0 "
            f"2>/dev/null | xargs -0 grep -l -F {token} 2>/dev/null | sed 's/^/holds-token /'",
            f"find / \\( -path /proc -o -path /sys \\) -prune -o -name '{MARKER}*' -print "
            "2>/dev/null | sed 's/^/marker /'",
            "echo commits $(git -C /work/repo cat-file --batch-all-objects --batch-check "
            "| grep -c ' commit ')",
            f"echo tree $({TREE_HASH})",
        ]
    )


def leave(token: str) -> str:
    places = " ".join(PLACES)
    return (
        f'for d in {places}; do echo {token} > "$d/{MARKER}"; done; '
        "cd /work/repo && f=$(git ls-files | head -n 1) && echo " + token + ' >> "$f" && '
        "git -c user.name=marker -c user.email=marker@localhost commit -q -a -m " + token
    )


def marker_model(token: str) -> Model:
    steps = [
        tool_call(MODEL, "bash", command=check(token)),
        tool_call(MODEL, "bash", command=leave(token)),
        tool_call(MODEL, "bash", command=check(token)),
        submit(MODEL),
    ]

    def policy(turn: Turn) -> ModelOutput:
        return steps[min(turn.step, len(steps) - 1)].model_copy(deep=True)

    return scripted_model(policy, "marker")


@scorer(metrics=[mean()])
def not_scored() -> Scorer:
    """E4 is about the agent's container; the hidden tests need not run."""

    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=0)

    return score


def pristine_tree_hash(task_id: str) -> str:
    """The container's TREE_HASH, computed on the host from the shipped snapshot."""
    files = read_tree(load_task(task_id).repo_dir)
    lines = "".join(
        f"{hashlib.sha256(data).hexdigest()}  ./{path}\n"
        for path, data in sorted(files.items(), key=lambda item: f"./{item[0]}".encode())
    )
    return hashlib.sha256(lines.encode()).hexdigest()


def parse_check(output: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {"holds-token": [], "marker": [], "commits": [], "tree": []}
    for line in output.splitlines():
        kind, _, rest = line.partition(" ")
        if kind in found:
            found[kind].append(rest)
    return found


@pytest.mark.docker
def test_consecutive_attempts_start_clean(docker_engine: None, tmp_path: Path) -> None:
    token = f"evalh-e4-{uuid.uuid4().hex}"
    tasks = one_task_per_language()
    task = task_with(evalh(task_ids=tasks, epochs=2), scorer=not_scored())
    log = run_eval(marker_model(token), log_dir=str(tmp_path), task=task, max_samples=1)
    attempts = {(str(s.id), s.epoch): s for s in samples(log)}
    assert sorted(attempts) == [(t, e) for t in tasks for e in (1, 2)]
    for task_id in tasks:
        first, second = attempts[task_id, 1], attempts[task_id, 2]
        # Consecutive: the second attempt started after the first ended.
        assert first.completed_at
        assert second.started_at
        assert datetime.fromisoformat(first.completed_at) <= datetime.fromisoformat(
            second.started_at
        )
        for sample in (first, second):
            before, _, after = bash_outputs(sample)
            start, end = parse_check(before), parse_check(after)
            assert start == {
                "holds-token": [],
                "marker": [],
                "commits": ["1"],
                "tree": [pristine_tree_hash(task_id)],
            }, (task_id, sample.epoch, before)
            # What the attempt left is visible to the check: a marker in each place, the token
            # in each marker, in the edited file and in git's logs, a second commit, a changed
            # tree.
            assert len(end["marker"]) == len(PLACES), (task_id, after)
            assert set(end["marker"]) <= set(end["holds-token"]), (task_id, after)
            assert len(end["holds-token"]) > len(PLACES), (task_id, after)
            assert end["commits"] == ["2"]
            assert end["tree"] != start["tree"]
