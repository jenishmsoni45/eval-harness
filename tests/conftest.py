"""Shared fixtures: the Docker engine, the risk-001 image, one oracle run, and the container
cleanup check (phases.md P1-9)."""

from __future__ import annotations

import socket
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from inspect_ai.log import EvalLog

from harness.containers import leftover_containers, remove_containers


def docker_available() -> bool:
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=30, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


@pytest.fixture(scope="session")
def docker_engine() -> None:
    """Docker tests fail, never skip, when the engine is unreachable."""
    if not docker_available():
        pytest.fail("this test needs a running Docker engine (start Docker Desktop)")


LOCAL_HOSTS = frozenset({None, "localhost", "127.0.0.1", "::1"})


@pytest.fixture(scope="session", autouse=True)
def no_internet() -> Iterator[None]:
    """No test, and no session fixture, may reach the internet from this process (D39): any
    library that tried to fetch something at run time fails the run. Docker is driven through its
    CLI in child processes, over its local socket, so it is unaffected."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def check(sock: socket.socket, address: Any) -> None:
        if sock.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in LOCAL_HOSTS:
            raise AssertionError(f"a test tried to connect to {address}: no downloads (D39)")

    def connect(sock: socket.socket, address: Any) -> None:
        check(sock, address)
        real_connect(sock, address)

    def connect_ex(sock: socket.socket, address: Any) -> int:
        check(sock, address)
        return real_connect_ex(sock, address)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host not in LOCAL_HOSTS:
            raise AssertionError(f"a test tried to resolve {host!r}: no downloads (D39)")
        return real_getaddrinfo(host, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket.socket, "connect", connect)
        patch.setattr(socket.socket, "connect_ex", connect_ex)
        patch.setattr(socket, "getaddrinfo", getaddrinfo)
        yield


@pytest.fixture(autouse=True)
def no_tokenizer_download(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test in which Inspect reaches for tiktoken, whose first use downloads a tokenizer
    file from the internet (D31)."""
    import tiktoken

    def refuse(name: str) -> Any:
        raise AssertionError(f"tiktoken.get_encoding({name!r}) called: it downloads a file")

    monkeypatch.setattr(tiktoken, "get_encoding", refuse)


@pytest.fixture(autouse=True)
def no_containers_left_behind(request: pytest.FixtureRequest) -> Iterator[None]:
    """After every Docker test, no evalh-* or inspect-evalh-* container may remain (P1-9).
    Leftovers are removed so one failure does not cascade, and the test errors."""
    yield
    if request.node.get_closest_marker("docker") is None:
        return
    left = leftover_containers()
    if left:
        remove_containers(left)
        pytest.fail(f"containers left behind: {left}")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """The same check once more at the end of the whole run, for every test."""
    if not docker_available():
        return
    left = leftover_containers()
    if left:
        remove_containers(left)
        sys.stderr.write(f"\ncontainers left behind after the test run: {left}\n")
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@dataclass(frozen=True)
class OracleRun:
    log: EvalLog
    tokenizer_calls: list[str]
    modules: frozenset[str]  # every module imported by the end of the run
    log_dir: Path


@pytest.fixture(scope="session")
def oracle_run(docker_engine: None, tmp_path_factory: pytest.TempPathFactory) -> OracleRun:
    """One oracle attempt on risk-001, shared by the tests that inspect it. tiktoken is made to
    raise for the whole run, so the run passing proves no tokenizer file was fetched (D31)."""
    import tiktoken

    from harness.agents.oracle import oracle_model
    from harness.eval import run_eval

    calls: list[str] = []

    def no_tokenizer(name: str) -> Any:
        calls.append(name)
        raise AssertionError(f"tiktoken.get_encoding({name!r}) called during a scripted run")

    log_dir = tmp_path_factory.mktemp("oracle-logs")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(tiktoken, "get_encoding", no_tokenizer)
        log = run_eval(oracle_model(), task_ids="risk-001", log_dir=str(log_dir))
    return OracleRun(log, calls, frozenset(sys.modules), log_dir)
