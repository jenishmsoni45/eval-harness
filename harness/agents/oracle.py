"""The oracle agent: always applies the task's reference fix (design.md 6).

It plays the honest agents' script with a success every time (harness/agents/honest.py): run the
visible tests, view each file the patch changes, write each change with text_editor, run the
visible tests again, submit.
"""

from __future__ import annotations

from inspect_ai.model import ModelOutput

from harness.agents import honest
from harness.agents.outcomes import Outcome

NAME = honest.ORACLE
MODEL = honest.model_id(NAME)
oracle_model = honest.oracle_model


def script(task_id: str) -> tuple[ModelOutput, ...]:
    return honest.script(NAME, task_id, Outcome.SUCCESS)
