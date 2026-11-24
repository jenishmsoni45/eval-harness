"""Every compose service has no network and every D21 limit (phases.md P1-5; design.md 2).

A custom compose file replaces Inspect's generated one, including its `network_mode: none`, so
each setting must be written out for each service (D27). Each service's init and keep-alive run as
root with only SETUID and SETGID, and the agent's tools run as `agent` (D60). The validator's plain
`docker run` applies the same settings, except that its one script runs as `agent` with no
capability at all: it has no keep-alive to protect and no tool helper to serve.
"""

from __future__ import annotations

import inspect
import os
import subprocess
from typing import Any

import pytest
import yaml

from harness.eval import COMPOSE_TEMPLATE, evalh, limited_agent
from harness.tasks import load_task
from harness.testrun import AGENT_USER
from scripts.validate_tasks import SANDBOX_FLAGS

EXPECTED: dict[str, Any] = {
    "image": "${SAMPLE_METADATA_IMAGE}",
    "x-local": True,
    "pull_policy": "never",
    "init": True,
    "command": ["sleep", "infinity"],
    "working_dir": "/work/repo",
    "user": "root",
    "network_mode": "none",
    "cpus": 1,
    "mem_limit": "2g",
    "memswap_limit": "2g",
    "pids_limit": 256,
    "cap_drop": ["ALL"],
    "cap_add": ["SETUID", "SETGID"],
    "security_opt": ["no-new-privileges:true"],
    "environment": {"TZ": "UTC", "LANG": "C.UTF-8", "PYTHONHASHSEED": "0"},
}
# Keys that could open a path out of the sandbox; none may appear.
FORBIDDEN_KEYS = frozenset(
    {
        "volumes", "ports", "expose", "networks", "privileged", "devices", "extra_hosts",
        "dns", "ipc", "pid", "userns_mode", "env_file", "build", "links", "external_links",
        "container_name", "group_add", "sysctls", "volumes_from", "secrets", "configs",
    }
)  # fmt: skip


def services() -> dict[str, dict[str, Any]]:
    config = yaml.safe_load(COMPOSE_TEMPLATE.read_text())
    assert set(config) == {"name", "services"}, "no top-level networks, volumes, secrets or configs"
    assert config["name"] == "evalh"
    result: dict[str, dict[str, Any]] = config["services"]
    return result


def test_there_are_exactly_the_agent_and_scorer_services() -> None:
    assert set(services()) == {"default", "scorer"}


@pytest.mark.parametrize("service", ["default", "scorer"])
def test_each_service_has_no_network_and_every_limit(service: str) -> None:
    assert services()[service] == EXPECTED


@pytest.mark.parametrize("service", ["default", "scorer"])
def test_no_service_has_a_way_out(service: str) -> None:
    assert not set(services()[service]) & FORBIDDEN_KEYS


def test_the_validator_runs_with_the_same_settings() -> None:
    s = EXPECTED
    assert set(SANDBOX_FLAGS) == {
        f"--network={s['network_mode']}",
        f"--user={AGENT_USER}",
        f"--cap-drop={s['cap_drop'][0]}",
        f"--security-opt={s['security_opt'][0]}",
        f"--pids-limit={s['pids_limit']}",
        f"--cpus={s['cpus']}",
        f"--memory={s['mem_limit']}",
        f"--memory-swap={s['memswap_limit']}",
        "--init",
        *(f"--env={k}={v}" for k, v in s["environment"].items()),
        f"--workdir={s['working_dir']}",
    }


def test_only_the_two_capabilities_the_tool_helper_needs_are_added() -> None:
    """D60: SETUID and SETGID let Inspect's text_editor helper, running as root, switch to `agent`.
    Nothing else is added, and no-new-privileges stays."""
    for service in services().values():
        assert service["cap_drop"] == ["ALL"]
        assert service["cap_add"] == ["SETUID", "SETGID"]
        assert "no-new-privileges:true" in service["security_opt"]


def test_the_agents_tools_run_as_the_agent_user() -> None:
    """D60: the containers' default user is root (for the init and keep-alive only), so each tool
    must name `agent`, or it would run as root."""
    source = inspect.getsource(limited_agent)
    assert "bash(user=AGENT_USER)" in source
    assert "text_editor(user=AGENT_USER)" in source
    assert AGENT_USER == "agent"


def test_every_sample_uses_the_template(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("harness.eval.build_task_image", lambda task: f"evalh-task-{task.id}:test")
    task = evalh()
    assert len(task.dataset) > 0
    for sample in task.dataset:
        assert sample.sandbox is not None
        assert (sample.sandbox.type, sample.sandbox.config) == ("docker", str(COMPOSE_TEMPLATE))
        assert sample.metadata is not None
        assert sample.metadata["image"] == f"evalh-task-{sample.id}:test"
        # The report reads the level and language from the logs (R2).
        t = load_task(str(sample.id))
        assert (sample.metadata["difficulty"], sample.metadata["language"]) == (
            t.difficulty,
            t.language,
        )


@pytest.mark.docker
def test_docker_compose_accepts_the_template(docker_engine: None) -> None:
    result = subprocess.run(
        ["docker", "compose", "--file", str(COMPOSE_TEMPLATE), "config", "--quiet"],
        env={**os.environ, "SAMPLE_METADATA_IMAGE": "evalh-task-check:0"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
