"""E3 (design.md 1, phases.md P3-2, D53): nothing the agent can read in its sandbox (files,
`.git`, environment variables, process list) contains hidden-test content, patch content,
`task.yaml` or the canary string.

The snoop cheater searches everything it can read and submits. Its tool outputs must contain none
of the task's hidden material: the canary, each bug test's name, and every line of at least 20
characters from a patch, a hidden test or `task.yaml` that the shipped repo does not already
contain. A positive control plants decoy hidden material where the agent can write and checks
that the snoop finds it, so a clean result means the search works, not that it looked nowhere.

Images are covered by validation rule V4 (build context, `docker history`, every file of a
container of the image). Tasks: the ones a pull request changes plus one per language, or all
with EVALH_E1_TASKS=all (D53).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from inspect_ai import task_with
from inspect_ai.log import EvalSample
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox

from harness.agents.snoop import COMMANDS, OUTPUT_BYTES, snoop_model
from harness.eval import evalh, run_eval
from harness.sample_identity import record_sample_identity
from harness.tasks import Task, canary, load_task, read_tree
from scripts.validate_tasks import MIN_PATTERN_LENGTH, leak_patterns
from tests.runs import bash_outputs, by_task, invariant_tasks, tool_events

TRUNCATED = "too long to be displayed"  # Inspect's note on a cut tool output


def distinctive_lines(text: str, pristine: set[str]) -> set[str]:
    return {
        line.strip()
        for line in text.splitlines()
        if len(line.strip()) >= MIN_PATTERN_LENGTH and line.strip() not in pristine
    }


def hidden_material(task: Task) -> list[str]:
    pristine = {
        line.strip()
        for data in read_tree(task.repo_dir).values()
        for line in data.decode(errors="replace").splitlines()
    }
    found = set(leak_patterns(task))
    for data in read_tree(task.hidden_tests_dir).values():
        found |= distinctive_lines(data.decode(errors="replace"), pristine)
    found |= distinctive_lines((task.path / "task.yaml").read_text(), pristine)
    return sorted(found)


def assert_the_snoop_searched(sample: EvalSample) -> list[str]:
    """Every search ran, nothing was cut off, and the outputs show it looked: its environment,
    and one commit in the repository's object database."""
    events = tool_events(sample)
    assert [e.function for e in events] == ["bash"] * len(COMMANDS) + ["submit"]
    assert all(e.error is None for e in events), sample.id
    outputs = bash_outputs(sample)
    for output in outputs:
        assert TRUNCATED not in output
        assert len(output.encode()) <= OUTPUT_BYTES + 1000
    assert "PYTHONHASHSEED=0" in outputs[0]
    assert "      1 commit" in outputs[2], outputs[2]
    return outputs


@pytest.mark.docker
def test_the_snoop_finds_no_hidden_material(docker_engine: None, tmp_path: Path) -> None:
    tasks = invariant_tasks()
    log = run_eval(snoop_model(), task_ids=tasks, log_dir=str(tmp_path))
    samples = by_task(log)
    assert sorted(samples) == tasks
    for task_id, sample in samples.items():
        outputs = assert_the_snoop_searched(sample)
        patterns = hidden_material(load_task(task_id))
        found = [(i, p) for i, out in enumerate(outputs) for p in patterns if p in out]
        assert found == [], (task_id, found)


DECOY_TASK = "risk-001"
# Paths inside the sandbox, where the agent can write.
DECOY_TEST = "/var/tmp/evalh-decoy/zz_hidden_1_test.py"  # noqa: S108
DECOY_NOTE = "/tmp/evalh-decoy/notes.txt"  # noqa: S108


@solver
def plant_decoy(files: dict[str, str]) -> Solver:
    """Test only: put hidden material where the agent can read it, before the agent starts."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        for path, text in files.items():
            await sandbox().write_file(path, text)
        return state

    return solve


@pytest.mark.docker
def test_the_snoop_finds_planted_hidden_material(docker_engine: None, tmp_path: Path) -> None:
    task = load_task(DECOY_TASK)
    bug_test = leak_patterns(task)
    name = next(p for p in bug_test if p.startswith("test_"))
    decoys = {
        DECOY_TEST: f"# {canary()}\ndef {name}():\n    pass\n",
        DECOY_NOTE: f"left behind: {canary()}\n",
    }
    planted = task_with(
        evalh(task_ids=[DECOY_TASK]), setup=[record_sample_identity(), plant_decoy(decoys)]
    )
    log = run_eval(snoop_model(), log_dir=str(tmp_path), task=planted)
    sample = by_task(log)[DECOY_TASK]
    everything = "\n".join(assert_the_snoop_searched(sample))
    assert canary() in everything
    assert name in everything
    assert DECOY_TEST in everything
