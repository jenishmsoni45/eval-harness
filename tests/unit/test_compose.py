"""Every compose service has no network and every D21 limit (phases.md P1-5; design.md 2).

A custom compose file replaces Inspect's generated one, including its `network_mode: none`, so
each setting must be written out for each service (D27). The validator's plain `docker run` must
apply the same settings.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

import pytest
import yaml

from harness.eval import COMPOSE_TEMPLATE, evalh
from scripts.validate_tasks import SANDBOX_FLAGS

EXPECTED: dict[str, Any] = {
    "image": "${SAMPLE_METADATA_IMAGE}",
    "x-local": True,
    "pull_policy": "never",
    "init": True,
    "command": ["sleep", "infinity"],
    "working_dir": "/work/repo",
    "user": "agent",
    "network_mode": "none",
    "cpus": 1,
    "mem_limit": "2g",
    "memswap_limit": "2g",
    "pids_limit": 256,
    "cap_drop": ["ALL"],
    "security_opt": ["no-new-privileges:true"],
    "environment": {"TZ": "UTC", "LANG": "C.UTF-8", "PYTHONHASHSEED": "0"},
}
# Keys that could open a path out of the sandbox; none may appear.
FORBIDDEN_KEYS = frozenset(
    {
        "volumes", "ports", "expose", "networks", "privileged", "cap_add", "devices", "extra_hosts",
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
        f"--user={s['user']}",
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


def test_every_sample_uses_the_template(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("harness.eval.build_task_image", lambda task: f"evalh-task-{task.id}:test")
    task = evalh()
    assert len(task.dataset) > 0
    for sample in task.dataset:
        assert sample.sandbox is not None
        assert (sample.sandbox.type, sample.sandbox.config) == ("docker", str(COMPOSE_TEMPLATE))
        assert sample.metadata is not None
        assert sample.metadata["image"] == f"evalh-task-{sample.id}:test"


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
