"""Fault injection for E6 (design.md 1 and 8, D18): infrastructure failures, injected into real
attempts.

- **A container that fails to start.** Inspect's Docker sandbox starts a sample's containers in
  `DockerSandboxEnvironment.sample_init`; `failing_starts` makes that raise for chosen tasks, a
  given number of times per task (or every time), the way a failed `docker compose up` surfaces.
- **A container killed mid-attempt.** `killing_model` plays an honest scripted agent and, on its
  first try at a chosen task, kills its own agent container from the host with `docker kill`
  before its second turn's tool call runs. The attempt then fails when its next text_editor call
  or the scorer reaches the dead container, and Inspect retries it (D79).

Only containers of the attempt's own `inspect-evalh-*` compose project are touched.
"""

from __future__ import annotations

import subprocess
from collections import Counter
from collections.abc import Callable, Collection, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any

import pytest
from inspect_ai.model import Model, ModelOutput
from inspect_ai.util import sandbox, store
from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment

from harness.agents.honest import output_at, plan
from harness.agents.outcomes import Outcome
from harness.agents.scripted import Turn, scripted_model
from harness.attempt import AGENT_INFO_KEY

START_FAILURE = "injected fault: the sample's containers failed to start"
# What Inspect's errors say about a container that has exited, whichever call meets it first:
# the scorer's own command (SandboxUnavailableError) or a tool's injection (SandboxInjectionError).
# A bash tool call into it is not an error at all: it comes back to the agent as a tool error
# (D79), so the attempt fails only once the scorer, or a text_editor call, reaches the container.
CONTAINER_GONE = "The sandbox is not running"
ALWAYS = 10**9


@contextmanager
def failing_starts(
    monkeypatch: pytest.MonkeyPatch, times: int, task_ids: Collection[str] | None = None
) -> Iterator[Counter[str]]:
    """While open, starting the sandbox of a matching task fails its first `times` tries (ALWAYS:
    every try). Yields the count of injected failures per task."""
    original: Callable[..., Any] = DockerSandboxEnvironment.sample_init.__func__  # type: ignore[attr-defined]
    injected: Counter[str] = Counter()

    async def sample_init(
        cls: type[DockerSandboxEnvironment], task_name: str, config: Any, metadata: dict[str, str]
    ) -> Any:
        task_id = str(metadata.get("task_id"))
        if (task_ids is None or task_id in task_ids) and injected[task_id] < times:
            injected[task_id] += 1
            raise RuntimeError(START_FAILURE)
        return await original(cls, task_name, config, metadata)

    with monkeypatch.context() as m:
        m.setattr(DockerSandboxEnvironment, "sample_init", classmethod(sample_init))
        yield injected


def kill_own_agent_container() -> str:
    """Kills the running sample's agent (`default`) container from the host; returns its name."""
    # sandbox() is Inspect's logging proxy; as_type() gives the Docker environment under it.
    project = sandbox().as_type(DockerSandboxEnvironment)._project.name
    if not project.startswith("inspect-evalh"):
        raise AssertionError(f"refusing to touch the compose project {project!r}")
    names = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            "label=com.docker.compose.service=default",
            "--format",
            "{{.Names}}",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    if len(names) != 1:
        raise AssertionError(f"expected one agent container in {project}, found {names}")
    subprocess.run(["docker", "kill", names[0]], capture_output=True, check=True)
    return names[0]


def killing_model(
    name: str, master_seed: int, kill_at_step: int = 1, task_ids: Collection[str] | None = None
) -> tuple[Model, Counter[str]]:
    """The honest scripted agent `name`, which on its first try at each matching task kills its
    own container before turn `kill_at_step`'s tool call. Returns the model and the kills made."""
    kills: Counter[str] = Counter()

    def policy(turn: Turn) -> ModelOutput:
        info = plan(name, master_seed, turn)
        if turn.step == 0:
            store().set(AGENT_INFO_KEY, asdict(info))
        matching = task_ids is None or turn.task_id in task_ids
        if turn.step == kill_at_step and matching and not kills[turn.task_id]:
            kill_own_agent_container()
            kills[turn.task_id] += 1
        return output_at(name, turn.task_id, Outcome(info.outcome), turn.step)

    return scripted_model(policy, name), kills
