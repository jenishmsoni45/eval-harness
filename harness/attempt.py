"""One attempt's limits and its record in the log (design.md 2 and 3, R5, D21, D51).

- The agent phase ends at `MAX_TURNS` turns (one tool call each) or `AGENT_TIME_LIMIT_S` seconds
  of wall time. Both are applied around the agent by the harness's solver, which notes in the
  sample's store which one was hit and how long the agent ran.
- Scoring runs its tests within `SCORING_TIME_LIMIT_S` seconds, enforced by the scorer itself,
  so reaching it is the agent's outcome and never an infrastructure failure (D51).
- Scripted agents write what they know about themselves (their true rate on the task, their
  seed and drawn outcome) under `AGENT_INFO_KEY`; a real model writes nothing there.

The scorer copies all of it into the score's metadata, which is the attempt's record.
"""

from __future__ import annotations

from typing import Any

from inspect_ai.model import ChatMessage, ChatMessageAssistant

MAX_TURNS = 30
AGENT_TIME_LIMIT_S = 600
SCORING_TIME_LIMIT_S = 300

# The name a limit has in the record: Inspect's own "turn" and "time" for the agent phase, and
# these for the scorer's: its time limit, and a process limit the agent filled so that nothing
# could start (D61).
SCORING_LIMIT = "scoring"
PROCESSES_LIMIT = "processes"

LIMIT_HIT_KEY = "evalh:limit_hit"
AGENT_SECONDS_KEY = "evalh:agent_seconds"
AGENT_INFO_KEY = "evalh:agent"


def tool_calls(messages: list[ChatMessage]) -> int:
    """The tool calls the agent made, submit included (the harness keeps submit calls in the
    conversation). A generation that went past the turn limit is never added to the
    conversation, so its call, which never ran, is not counted."""
    return sum(len(m.tool_calls or []) for m in messages if isinstance(m, ChatMessageAssistant))


def bash_commands(messages: list[ChatMessage]) -> list[str]:
    """The agent's bash commands, in order, for the snooping check (design.md 4)."""
    return [
        str(call.arguments.get("command", ""))
        for m in messages
        if isinstance(m, ChatMessageAssistant)
        for call in m.tool_calls or []
        if call.function == "bash"
    ]


def agent_record(store: Any, messages: list[ChatMessage]) -> dict[str, Any]:
    """The agent phase's part of the record, from the sample's store and conversation."""
    limit = store.get(LIMIT_HIT_KEY)
    return {
        "limits_hit": [limit] if limit else [],
        "tool_calls": tool_calls(messages),
        "agent_seconds": store.get(AGENT_SECONDS_KEY),
        "agent": store.get(AGENT_INFO_KEY),
    }
