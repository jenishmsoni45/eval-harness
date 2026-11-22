"""The Inspect behaviour the design depends on (D27, phases.md P1-6). If one of these fails, the
phase stops for a decision.

- A `mockllm` callable can read the sample's task id and epoch from `store()`.
- The sandbox-tools helper behind `text_editor` ships in the wheel for amd64 and arm64, so
  Inspect never downloads it; and `text_editor` works in a container with no network.
- Compose projects are named `inspect-evalh-i<random>` (D25), and none remains after a sample.

The Docker test runs on the host's architecture: arm64 on the Mac, amd64 in CI.
"""

from __future__ import annotations

import platform
import re
from pathlib import Path

import inspect_ai
import pytest
from inspect_ai import Task
from inspect_ai import eval as inspect_eval
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.event import ToolEvent
from inspect_ai.model import ChatMessageTool, ModelOutput
from inspect_ai.solver import generate
from inspect_ai.util._sandbox.docker.util import task_project_name

from harness.agents.scripted import Turn, scripted_model, submit, tool_call
from harness.containers import leftover_containers
from harness.eval import TASK_NAME, run_eval
from harness.sample_identity import record_sample_identity

PROBE = "mockllm/probe"
# Prints the number of IPv4 routes in the main table, then the state of every interface but lo.
NETWORK_PROBE = (
    "awk 'NR > 1' /proc/net/route | wc -l; "
    'for i in /sys/class/net/*; do [ -d "$i" ] && [ "${i##*/}" != lo ] && cat "$i/operstate"; '
    "done | sort -u"
)
MACHINE = {"arm64": "aarch64", "aarch64": "aarch64", "x86_64": "x86_64", "amd64": "x86_64"}


def test_store_is_readable_from_the_mockllm_callable(tmp_path: Path) -> None:
    def policy(turn: Turn) -> ModelOutput:
        return ModelOutput.from_content(model=PROBE, content=f"{turn.task_id}@{turn.epoch}")

    task = Task(
        dataset=MemoryDataset([Sample(id="alpha", input="a"), Sample(id="beta", input="b")]),
        setup=record_sample_identity(),
        solver=generate(),
        epochs=2,
    )
    [log] = inspect_eval(
        task, model=scripted_model(policy, "probe"), log_dir=str(tmp_path), display="none"
    )
    assert log.status == "success"
    assert log.samples is not None
    seen = {(s.id, s.epoch): s.output.completion for s in log.samples}
    assert seen == {(i, e): f"{i}@{e}" for i in ("alpha", "beta") for e in (1, 2)}


def test_the_sandbox_tools_helper_ships_for_both_architectures() -> None:
    package = Path(inspect_ai.__file__).parent
    version_file = package / "tool" / "_sandbox_tools_utils" / "sandbox_tools_version.txt"
    version = version_file.read_text().strip()
    for arch in ("amd64", "arm64"):
        assert (package / "binaries" / f"inspect-sandbox-tools-{arch}-v{version}").is_file()


def test_compose_projects_are_named_inspect_evalh() -> None:
    assert re.fullmatch(r"inspect-evalh-i[a-z0-9]{6}", task_project_name(TASK_NAME))


@pytest.mark.docker
def test_text_editor_works_offline_and_no_container_remains(
    docker_engine: None, tmp_path: Path
) -> None:
    probe = "/tmp/evalh-probe.txt"  # noqa: S108 (inside the sandbox)
    during: list[str] = []
    steps = [
        tool_call(PROBE, "text_editor", command="create", path=probe, file_text="alpha\n"),
        tool_call(
            PROBE, "text_editor", command="str_replace", path=probe, old_str="alpha", new_str="beta"
        ),
        tool_call(PROBE, "text_editor", command="view", path=probe),
        tool_call(PROBE, "bash", command=f"cat {probe}; uname -m; {NETWORK_PROBE}"),
        submit(PROBE),
    ]  # fmt: skip

    def policy(turn: Turn) -> ModelOutput:
        if turn.step == 0:
            during.extend(leftover_containers())  # runs on the host, mid-sample
        return steps[min(turn.step, len(steps) - 1)].model_copy(deep=True)

    log = run_eval(scripted_model(policy, "probe"), task_ids="risk-001", log_dir=str(tmp_path))
    assert log.status == "success", log.error
    assert log.samples is not None
    tools = [m for m in log.samples[0].messages if isinstance(m, ChatMessageTool)]
    # The harness keeps the submit call and its tool message in the conversation (react()
    # would drop them), so the attempt's record can count every tool call (harness/eval.py).
    assert [m.function for m in tools] == ["text_editor"] * 3 + ["bash", "submit"]
    assert [m.error for m in tools] == [None] * 5
    calls = [e.function for e in log.samples[0].events if isinstance(e, ToolEvent)]
    assert calls == ["text_editor"] * 3 + ["bash", "submit"]
    assert "beta" in tools[2].text
    # On the host's architecture, with no route and no interface up but loopback (network_mode:
    # none). Phase 3's E2 probe tries real connections.
    lines = tools[3].text.split()
    assert lines[:3] == ["beta", MACHINE[platform.machine()], "0"]
    assert set(lines[3:]) <= {"down"}

    # Mid-sample: one compose project, inspect-evalh-i<random>, with the agent and scorer.
    projects = {re.sub(r"-(default|scorer)-1$", "", name) for name in during}
    assert len(projects) == 1
    assert re.fullmatch(r"inspect-evalh-i[a-z0-9]{6}", projects.pop())
    assert sorted(name.rsplit("-", 2)[1] for name in during) == ["default", "scorer"]
    # After the sample: nothing left.
    assert leftover_containers() == []
