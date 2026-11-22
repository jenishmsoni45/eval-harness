"""Helpers shared by the tests that run attempts in sandboxes."""

from __future__ import annotations

import os
from typing import Any

from inspect_ai.event import ToolEvent
from inspect_ai.log import EvalLog, EvalSample

from harness.tasks import load_task, task_ids
from scripts.validate_tasks import changed_task_ids


def one_task_per_language() -> list[str]:
    """The first task of each language, as pull-request CI runs the E2-E6 tests (D15)."""
    first: dict[str, str] = {}
    for task_id in task_ids():
        first.setdefault(load_task(task_id).language, task_id)
    return sorted(first.values())


def invariant_tasks() -> list[str]:
    """Every task with EVALH_E1_TASKS=all (the "validate all" workflow); otherwise the tasks
    changed since EVALH_BASE_REF (default origin/main) plus one per language (D53)."""
    if os.environ.get("EVALH_E1_TASKS") == "all":
        return task_ids()
    changed = changed_task_ids(os.environ.get("EVALH_BASE_REF", "origin/main"))
    return sorted({*changed, *one_task_per_language()})


def samples(log: EvalLog) -> list[EvalSample]:
    assert log.status == "success", log.error
    assert log.samples is not None
    return log.samples


def by_task(log: EvalLog) -> dict[str, EvalSample]:
    return {str(s.id): s for s in samples(log)}


def record(sample: EvalSample) -> dict[str, Any]:
    """The attempt's record: the metadata of its one score."""
    assert sample.scores is not None
    [score] = sample.scores.values()
    assert score.metadata is not None
    return score.metadata


def base(sample: EvalSample) -> float:
    return float(record(sample)["base"])


def tool_events(sample: EvalSample) -> list[ToolEvent]:
    return [e for e in sample.events if isinstance(e, ToolEvent)]


def bash_outputs(sample: EvalSample) -> list[str]:
    """The output of each bash call, in order."""
    return [str(e.result) for e in tool_events(sample) if e.function == "bash"]
