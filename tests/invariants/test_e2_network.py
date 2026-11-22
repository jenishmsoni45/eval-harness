"""E2 (design.md 1, phases.md P3-1, D54): no process in either container of an attempt can
resolve a name or open a connection to any address outside its container.

- The network probe agent runs its checks in the agent's container through its own bash tool:
  DNS lookups, TCP to public IP literals and to Docker's host addresses, and HTTP to a name and to
  an IP literal. Each must fail the way a missing network makes it fail. The loopback interface
  must be the only one that is up, has an address or has a route; the kernel's fallback tunnel
  devices exist in every network namespace, down and unaddressed (D57).
- The same script runs in the scoring container, which no tool reaches, from a test scorer.
- A static check: every service in the compose template has `network_mode: none` and nothing
  that would add a network, a port, a DNS server or a host entry.

Run on one task per language, as pull-request CI runs the E2-E6 tests (D15).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from inspect_ai import task_with
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from harness.agents.probe import CHECKS, EXPECTED_FAILURES, PROBE_SCRIPT, parse, probe_model
from harness.eval import COMPOSE_TEMPLATE, evalh, run_eval
from harness.testrun import AGENT_USER
from tests.runs import bash_outputs, one_task_per_language, record, samples

NETWORK_KEYS = {"networks", "ports", "expose", "dns", "dns_search", "extra_hosts", "links"}


def test_every_compose_service_has_no_network() -> None:
    compose: dict[str, Any] = yaml.safe_load(COMPOSE_TEMPLATE.read_text())
    assert "networks" not in compose
    assert compose["services"]
    for name, service in compose["services"].items():
        assert service["network_mode"] == "none", name
        assert not NETWORK_KEYS & set(service), name


@scorer(metrics=[mean()])
def probe_the_scoring_container() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        result = await sandbox("scorer").exec(
            ["bash", "-c", PROBE_SCRIPT], user=AGENT_USER, timeout=300, timeout_retry=False
        )
        return Score(value=0, metadata={"output": result.stdout, "stderr": result.stderr})

    return score


def assert_no_network(where: str, output: str) -> None:
    state = parse(output)
    assert set(state.codes) == {name for name, _ in CHECKS}, (where, output)
    for name, code in state.codes.items():
        kind = name.split("-")[0]
        assert code in EXPECTED_FAILURES[kind], f"{where}: {name} exited {code}"
    assert "lo" in state.flags, (where, output)
    assert state.up == ["lo"], (where, state.flags)
    assert state.ipv6_addresses == ["lo"], where
    assert set(state.ipv6_routes) <= {"lo"}, where
    assert state.ipv4_routes == 0, where
    assert state.addresses_status == 0, where  # hostname ran, so no address is real
    assert state.addresses == [], where


@pytest.mark.docker
def test_no_container_of_an_attempt_reaches_the_network(
    docker_engine: None, tmp_path: Path
) -> None:
    tasks = one_task_per_language()
    task = task_with(evalh(task_ids=tasks), scorer=probe_the_scoring_container())
    log = run_eval(probe_model(), log_dir=str(tmp_path), task=task)
    seen = []
    for sample in samples(log):
        [agent_output] = bash_outputs(sample)
        assert_no_network(f"{sample.id} agent container", agent_output)
        assert_no_network(f"{sample.id} scoring container", record(sample)["output"])
        seen.append(str(sample.id))
    assert sorted(seen) == tasks
