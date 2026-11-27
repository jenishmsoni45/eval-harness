"""The RL environment's containers (architecture.md "RL episode", D25, D85).

The environment runs outside Inspect, so it starts each episode's two services itself, as compose
project `evalh-rl-<random>` from the eval's own template (harness/sandbox/compose.yaml), with
the same image, user, limits and `network_mode: none`. `close()` takes the project down with its
volumes, so no container outlives the episode.

`DockerExecSandbox` gives the scorer the three calls it uses (`exec`, `read_file`,
`write_file`) on `docker exec`, by subclassing Inspect's public `SandboxEnvironment`. It follows
Inspect's Docker sandbox where the scorer depends on it (D85):

- `exec` wraps a timed command in the in-container `/usr/bin/timeout -k 5s`, and exit 124, or
  137 or 143 once the time has run out, raises `TimeoutError`;
- commands run as the requested user, in /work/repo unless told otherwise;
- `write_file` creates parent directories;
- `read_file` raises `FileNotFoundError`, `IsADirectoryError` and `PermissionError`;
- a container that is no longer running raises `SandboxUnavailableError`, which the scorer
  passes on: an infrastructure failure, never a score.

Any difference from the eval would show up in `tests/unit/test_rl_env.py`, which checks that an
episode's reward equals the eval scorer's for the same changes.
"""

from __future__ import annotations

import asyncio
import base64
import os
import posixpath
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal, overload

from inspect_ai.util import (
    ExecResult,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    SandboxUnavailableError,
)

from harness.tasks import REPO_ROOT
from harness.testrun import REPO_DIR

COMPOSE_TEMPLATE = REPO_ROOT / "harness" / "sandbox" / "compose.yaml"
PROJECT_PREFIX = "evalh-rl-"
SERVICES = ("default", "scorer")
# Inspect's slack between the in-container timeout and the host's (docker.py): the in-container
# one takes up to timeout + 5 s with its SIGKILL grace.
HOST_TIMEOUT_SLACK_S = 10
TIMEOUT_EXIT_CODES = (124, 137, 143)
# How long `docker compose up` and `down` may take before the environment gives up.
COMPOSE_TIMEOUT_S = 120
DAEMON_ERRORS = ("Error response from daemon", "No such container", "is not running")


class DockerExecSandbox(SandboxEnvironment):
    """One running container, reached with `docker exec`."""

    def __init__(self, container: str, working_dir: str = REPO_DIR) -> None:
        super().__init__()
        self.container = container
        self.working_dir = working_dir

    def _path(self, file: str) -> str:
        return file if posixpath.isabs(file) else posixpath.join(self.working_dir, file)

    async def _run(
        self,
        cmd: list[str],
        *,
        stdin: bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
    ) -> tuple[int, bytes, bytes]:
        args = ["docker", "exec", "--workdir", self._path(cwd or self.working_dir)]
        if stdin is not None:
            args.append("--interactive")
        if user:
            args += ["--user", user]
        for key, value in (env or {}).items():
            args += ["--env", f"{key}={value}"]
        inner = cmd if timeout is None else ["/usr/bin/timeout", "-k", "5s", f"{timeout}s", *cmd]
        process = await asyncio.create_subprocess_exec(
            *args,
            self.container,
            *inner,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        start = time.monotonic()
        host_timeout = None if timeout is None else timeout + HOST_TIMEOUT_SLACK_S
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(stdin), host_timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise TimeoutError(f"Command timed out after {timeout} seconds") from None
        code = process.returncode if process.returncode is not None else -1
        if (
            timeout is not None
            and code in TIMEOUT_EXIT_CODES
            and (code == 124 or time.monotonic() - start >= timeout)
        ):
            raise TimeoutError(f"Command timed out after {timeout} seconds")
        # The command's own output could say the same, so ask Docker before calling it an
        # infrastructure failure, as Inspect does.
        if (
            code != 0
            and any(e in stderr.decode(errors="replace") for e in DAEMON_ERRORS)
            and not container_running(self.container)
        ):
            raise SandboxUnavailableError(
                f"The sandbox is not running and cannot execute: {self.container} has exited"
            )
        return code, stdout, stderr

    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,  # noqa: A002 (Inspect's name for it)
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        data = input.encode() if isinstance(input, str) else input
        code, stdout, stderr = await self._run(
            cmd, stdin=data, cwd=cwd, env=env, user=user, timeout=timeout
        )
        return ExecResult(
            success=code == 0,
            returncode=code,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
        )

    async def write_file(
        self, file: str, contents: str | bytes, *, user: str | None = None
    ) -> None:
        path = self._path(file)
        parent = posixpath.dirname(path)
        if parent:
            code, _, stderr = await self._run(["mkdir", "-p", parent], user=user)
            if code != 0:
                _raise_for(stderr, path, "write")
        data = contents.encode() if isinstance(contents, str) else contents
        code, _, stderr = await self._run(
            ["/bin/sh", "-c", 'base64 -d > "$1"', "sh", path],
            stdin=base64.b64encode(data),
            user=user,
        )
        if code != 0:
            _raise_for(stderr, path, "write")

    @overload
    async def read_file(
        self, file: str, text: Literal[True] = True, *, user: str | None = None
    ) -> str: ...

    @overload
    async def read_file(
        self, file: str, text: Literal[False], *, user: str | None = None
    ) -> bytes: ...

    async def read_file(
        self, file: str, text: bool = True, *, user: str | None = None
    ) -> str | bytes:
        path = self._path(file)
        code, stdout, stderr = await self._run(["cat", "--", path], user=user)
        if code != 0:
            _raise_for(stderr, path, "read")
        return stdout.decode("utf-8") if text else stdout

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        """Not used: the episode's compose project removes its containers (`Project.down`)."""


def _raise_for(stderr: bytes, path: str, action: str) -> None:
    message = stderr.decode(errors="replace")
    lowered = message.casefold()
    if "no such file or directory" in lowered:
        raise FileNotFoundError(2, "No such file or directory.", path)
    if "is a directory" in lowered:
        raise IsADirectoryError(21, "Is a directory.", path)
    if "permission denied" in lowered:
        raise PermissionError(13, "Permission denied.", path)
    raise RuntimeError(f"failed to {action} {path}: {message.strip()}")


def container_running(container: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", container],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


@dataclass
class Project:
    """One episode's compose project: the eval's two services from the eval's template."""

    image: str
    name: str = field(default_factory=lambda: f"{PROJECT_PREFIX}{uuid.uuid4().hex[:12]}")

    def _compose(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "docker",
                "compose",
                "--project-name",
                self.name,
                "--file",
                str(COMPOSE_TEMPLATE),
                *args,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=COMPOSE_TIMEOUT_S,
            env=_compose_env(self.image),
        )

    def up(self) -> dict[str, DockerExecSandbox]:
        """Start both services and wait until they run; on failure, remove what started."""
        result = self._compose("up", "--detach", "--wait", "--no-build")
        if result.returncode != 0:
            self.down()
            raise RuntimeError(f"could not start {self.name}: {result.stderr.strip()[-2000:]}")
        listed = self._compose("ps", "--format", "{{.Service}} {{.Name}}")
        names = dict(line.split(" ", 1) for line in listed.stdout.splitlines() if " " in line)
        missing = [s for s in SERVICES if s not in names]
        if listed.returncode != 0 or missing:
            self.down()
            raise RuntimeError(f"{self.name} is missing services {missing}")
        return {service: DockerExecSandbox(names[service]) for service in SERVICES}

    def down(self) -> None:
        """Remove every container and volume of the project; safe to call more than once."""
        self._compose("down", "--volumes", "--remove-orphans", "--timeout", "0")


def _compose_env(image: str) -> dict[str, str]:
    # The template takes its image from ${SAMPLE_METADATA_IMAGE}, as Inspect fills it per sample.
    return {**os.environ, "SAMPLE_METADATA_IMAGE": image}
