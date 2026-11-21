"""The task id and epoch of the running sample, for scripted agents (D27).

A `mockllm` callable receives the conversation, the tools, the tool choice and the generation
config, but not which sample it is serving. The setup solver below writes the task id and epoch
into Inspect's per-sample store before the agent starts; scripted agents read them back with
`store()`.
"""

from __future__ import annotations

from inspect_ai.solver import Generate, Solver, TaskState, solver

TASK_ID_KEY = "evalh:task_id"
EPOCH_KEY = "evalh:epoch"


@solver
def record_sample_identity() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.store.set(TASK_ID_KEY, str(state.sample_id))
        state.store.set(EPOCH_KEY, state.epoch)
        return state

    return solve
