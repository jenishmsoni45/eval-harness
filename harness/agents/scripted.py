"""Turning a scripted policy into an Inspect `mockllm` model (D27).

A policy is a plain function from the current turn to the next model output. The wrapper reads
the sample's task id and epoch from Inspect's store (written by the harness's setup solver),
counts the turns so far, and makes sure every output carries token usage.

Why usage: when an output has none, `mockllm` estimates it with tiktoken, which downloads a
tokenizer file from the internet on first use. Setting usage keeps a scripted run fully offline
(decisions.md D31).
"""

from __future__ import annotations

import shlex
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    GenerateConfig,
    Model,
    ModelOutput,
    ModelUsage,
    get_model,
)
from inspect_ai.tool import ToolChoice, ToolInfo
from inspect_ai.util import store

from harness.sample_identity import EPOCH_KEY, TASK_ID_KEY
from harness.testrun import REPO_DIR

MODEL_NAME_PREFIX = "mockllm/"


@dataclass(frozen=True)
class Turn:
    task_id: str
    epoch: int
    step: int  # how many turns the agent has already taken in this attempt
    messages: Sequence[ChatMessage]


Policy = Callable[[Turn], ModelOutput]


def scripted_model(policy: Policy, name: str) -> Model:
    """A `mockllm/<name>` model whose every output comes from policy."""

    def outputs(
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        turn = Turn(
            task_id=str(store().get(TASK_ID_KEY)),
            epoch=int(store().get(EPOCH_KEY)),
            step=sum(isinstance(m, ChatMessageAssistant) for m in messages),
            messages=messages,
        )
        output = policy(turn)
        if output.usage is None:
            output.usage = ModelUsage(input_tokens=0, output_tokens=0, total_tokens=0)
        return output

    return get_model(f"{MODEL_NAME_PREFIX}{name}", custom_outputs=outputs, memoize=False)


def tool_call(model: str, tool: str, **arguments: Any) -> ModelOutput:
    return ModelOutput.for_tool_call(model=model, tool_name=tool, tool_arguments=arguments)


def run_in_repo(model: str, command: Sequence[str]) -> ModelOutput:
    return tool_call(model, "bash", cmd=f"cd {REPO_DIR} && {shlex.join(command)}")


def submit(model: str, answer: str = "done") -> ModelOutput:
    return tool_call(model, "submit", answer=answer)
