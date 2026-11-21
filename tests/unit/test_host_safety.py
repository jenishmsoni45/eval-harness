"""Nothing this project does is a problem for the Mac it runs on (D39).

- No test can reach the internet: the session-wide guard in tests/conftest.py refuses any
  connection or name lookup outside localhost, so a library that fetched something at run time
  would fail the suite.
- No code starts a container that outlives its command: every `docker run` uses `--rm` and
  never detaches, and the compose template has no restart policy (Inspect removes each sample's
  project when the sample ends, D27).
"""

from __future__ import annotations

import ast
import socket

import pytest
import yaml

from harness.eval import COMPOSE_TEMPLATE
from harness.tasks import REPO_ROOT

CODE_DIRS = ("harness", "scripts", "stats", "rl")
DETACH_FLAGS = frozenset({"-d", "--detach", "--restart"})


def test_the_internet_guard_refuses_connections_and_lookups() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(AssertionError, match="D39"):
            sock.connect(("192.0.2.1", 443))  # TEST-NET-1: never routed anyway
        with pytest.raises(AssertionError, match="D39"):
            sock.connect_ex(("192.0.2.1", 443))
    with pytest.raises(AssertionError, match="D39"):
        socket.getaddrinfo("pypi.org", 443)


def docker_run_calls(source: str) -> list[list[str]]:
    """The string elements of every list literal that starts with "docker", "run"."""
    calls = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.List):
            items = [e.value for e in node.elts if isinstance(e, ast.Constant)]
            if items[:2] == ["docker", "run"]:
                calls.append([str(i) for i in items])
    return calls


def test_every_docker_run_removes_its_container_and_never_detaches() -> None:
    files = [
        p for d in CODE_DIRS if (REPO_ROOT / d).is_dir() for p in (REPO_ROOT / d).rglob("*.py")
    ]
    calls = {str(p.relative_to(REPO_ROOT)): docker_run_calls(p.read_text()) for p in files}
    found = [c for cs in calls.values() for c in cs]
    assert found, "expected the validator's docker run"
    for call in found:
        assert "--rm" in call, call
        assert not DETACH_FLAGS & set(call), call


def test_the_check_reads_docker_run_lists() -> None:
    assert docker_run_calls('x = ["docker", "run", "--rm", "-d", img]') == [
        ["docker", "run", "--rm", "-d"]
    ]
    assert docker_run_calls('x = ["docker", "build", "."]') == []


def test_no_compose_service_restarts_or_outlives_its_sample() -> None:
    services = yaml.safe_load(COMPOSE_TEMPLATE.read_text())["services"]
    for name, service in services.items():
        assert "restart" not in service, name
        assert "volumes" not in service, name


def test_the_container_leak_check_only_touches_this_projects_names() -> None:
    from harness.containers import PREFIXES, remove_containers

    assert PREFIXES == ("evalh-", "inspect-evalh-")
    with pytest.raises(ValueError, match="not owned by this project"):
        remove_containers(["evalh-ok", "jobqueue-api-1"])
