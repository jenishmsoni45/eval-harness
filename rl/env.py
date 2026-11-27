"""The eval's tasks as RL environments (requirements.md R6 to R8, architecture.md "RL episode").

    with Env() as env:
        observation = env.reset("risk-001", seed=7)
        result = env.step(Run("cd /work/repo && python -m pytest -q tests/visible"))
        ...
        result = env.step(Submit())  # result.done, result.reward, result.flags

- `reset(task_id, seed)` starts a fresh compose project from the task's image, the same two
  services, limits and template as an eval attempt (rl/sandbox.py), and returns the eval's first
  message (the fixed preamble and `instructions.md`) followed by a listing of the repo. Every
  episode starts from the pristine image, so E4 holds for episodes as for attempts (R8). The
  environment draws nothing at random: `seed` is recorded and is the policy's to use.
- `step(action)` runs one tool action in the agent's container as the `agent` user: a shell
  command, viewing a file or directory, creating a file, replacing a string, or submitting. Its
  observation is the action's output, as the eval's `bash` and `text_editor` tools would show it.
- The episode ends on submit, after `MAX_TURNS` actions, or once `AGENT_TIME_LIMIT_S` seconds
  have passed. Then the eval's own scorer (`harness.scorer.score_attempt`) scores it, with the
  episode's shell commands for the snooping check, and the containers are removed. The final
  observation carries only the reward and the flags; no observation ever contains the hidden
  tests' names, content or output, which reach only the scorer container (R6).
- `close()` removes the episode's containers and volumes; it is safe to call at any time.

A Docker error (a container that will not start or has died) is raised, never scored, as in the
eval (design.md 8); the caller closes the environment and may start the episode again.
"""

from __future__ import annotations

import asyncio
import math
import posixpath
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from types import TracebackType

from harness.attempt import AGENT_TIME_LIMIT_S, MAX_TURNS, SCORING_TIME_LIMIT_S
from harness.eval import prompt
from harness.images import build_task_image
from harness.scorer import score_attempt
from harness.tasks import IGNORED_DIRS, Task, is_ignored, load_task
from harness.testrun import AGENT_USER, REPO_DIR
from rl.sandbox import DockerExecSandbox, Project

# Inspect's default limit on one tool output (GenerateConfig.max_tool_output).
MAX_OUTPUT_BYTES = 16 * 1024


@dataclass(frozen=True)
class Run:
    """Run a shell command with bash, as the eval's `bash` tool does."""

    command: str


@dataclass(frozen=True)
class View:
    """Show a file with line numbers, or list a directory."""

    path: str


@dataclass(frozen=True)
class Create:
    """Write a file, creating its parent directories."""

    path: str
    file_text: str


@dataclass(frozen=True)
class Replace:
    """Replace the one occurrence of `old_str` in a file with `new_str`."""

    path: str
    old_str: str
    new_str: str


@dataclass(frozen=True)
class Submit:
    """End the episode and have it scored."""

    answer: str = "done"


Action = Run | View | Create | Replace | Submit


@dataclass(frozen=True)
class StepResult:
    observation: str
    done: bool
    reward: float | None = None  # only when done
    flags: tuple[str, ...] = ()  # only when done


@dataclass
class Episode:
    """What `run_episode` played: the actions in order, each observation, and the outcome."""

    task_id: str
    seed: int | None
    actions: list[Action] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    reward: float | None = None
    flags: tuple[str, ...] = ()


Policy = Callable[[str], Action]


class Env:
    """One task at a time; `reset` ends any episode still running."""

    def __init__(
        self,
        max_steps: int = MAX_TURNS,
        time_limit_s: float = AGENT_TIME_LIMIT_S,
        scoring_limit_s: float = SCORING_TIME_LIMIT_S,
    ) -> None:
        self.max_steps = max_steps
        self.time_limit_s = time_limit_s
        self.scoring_limit_s = scoring_limit_s
        self.task: Task | None = None
        self.seed: int | None = None
        self._runner = asyncio.Runner()
        self._project: Project | None = None
        self._boxes: dict[str, DockerExecSandbox] = {}
        self._commands: list[str] = []
        self._steps = 0
        self._started = 0.0
        self._done = True

    # --- The interface ----------------------------------------------------------------------

    def reset(self, task_id: str, seed: int | None = None) -> str:
        self.close()
        task = load_task(task_id)
        project = Project(build_task_image(task))
        self._project = project
        self._boxes = project.up()
        self.task, self.seed = task, seed
        self._commands, self._steps, self._done = [], 0, False
        self._started = time.monotonic()
        listing = self._runner.run(self._listing())
        return f"{prompt(task.visible_command, task.instructions)}\nFiles in {REPO_DIR}:\n{listing}"

    def step(self, action: Action) -> StepResult:
        if self._done or self.task is None:
            raise RuntimeError("no episode is running: call reset first")
        if not isinstance(action, Run | View | Create | Replace | Submit):
            raise TypeError(f"not an action: {action!r}")
        if self._remaining() <= 0:
            return self._finish()
        if isinstance(action, Submit):
            self._steps += 1
            return self._finish()
        self._steps += 1
        try:
            output = self._runner.run(self._act(action))
        except TimeoutError:
            return self._finish()  # the episode's time ran out during the command
        if self._steps >= self.max_steps:
            return self._finish()
        return StepResult(_truncate(output), done=False)

    @property
    def project_name(self) -> str | None:
        """The running episode's compose project; its containers' names start with it."""
        return self._project.name if self._project is not None else None

    def close(self) -> None:
        if self._project is not None:
            self._project.down()
            self._project = None
        self._boxes = {}
        self._done = True

    def __enter__(self) -> Env:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
        self._runner.close()

    # --- Inside an episode ------------------------------------------------------------------

    def _remaining(self) -> float:
        return self.time_limit_s - (time.monotonic() - self._started)

    def _finish(self) -> StepResult:
        """Score the episode with the eval's scorer, remove its containers, and report only the
        reward and the flags."""
        if self.task is None:
            raise RuntimeError("no episode is running")
        try:
            score = self._runner.run(
                score_attempt(
                    self._boxes["default"],
                    self._boxes["scorer"],
                    self.task,
                    self._commands,
                    self.scoring_limit_s,
                )
            )
        finally:
            self.close()
        if not isinstance(score.value, int | float):
            raise TypeError(f"the scorer gave a non-numeric reward: {score.value!r}")
        reward = float(score.value)
        flags = tuple((score.metadata or {}).get("flags", []))
        shown = ", ".join(flags) or "none"
        observation = f"The episode is over. Reward: {reward:g}. Flags: {shown}."
        return StepResult(observation, done=True, reward=reward, flags=flags)

    async def _act(self, action: Run | View | Create | Replace) -> str:
        box = self._boxes["default"]
        if isinstance(action, Run):
            self._commands.append(action.command)
            timeout = max(math.ceil(self._remaining()), 1)
            result = await box.exec(
                ["bash", "--login", "-c", action.command], user=AGENT_USER, timeout=timeout
            )
            return (f"{result.stderr}\n" if result.stderr else "") + result.stdout
        path = _absolute(action.path)
        try:
            if isinstance(action, View):
                return await self._view(box, path)
            if isinstance(action, Create):
                await box.write_file(path, action.file_text, user=AGENT_USER)
                return f"File created successfully at: {path}"
            return await self._replace(box, path, action.old_str, action.new_str)
        except (FileNotFoundError, IsADirectoryError, PermissionError, UnicodeDecodeError) as e:
            return f"Error: {type(e).__name__}: {path}"

    async def _view(self, box: DockerExecSandbox, path: str) -> str:
        listing = await box.exec(
            ["find", path, "-maxdepth", "2", "-not", "-path", "*/.*"], user=AGENT_USER
        )
        if listing.success and listing.stdout.strip() != path:
            entries = sorted(listing.stdout.splitlines())
            return f"Files and directories up to 2 levels deep in {path}:\n" + "\n".join(entries)
        text = await box.read_file(path, user=AGENT_USER)
        numbered = "\n".join(f"{n:6}\t{line}" for n, line in enumerate(text.split("\n"), 1))
        return f"Here's the result of running `cat -n` on {path}:\n{numbered}"

    async def _replace(self, box: DockerExecSandbox, path: str, old: str, new: str) -> str:
        text = await box.read_file(path, user=AGENT_USER)
        found = text.count(old)
        if found != 1:
            where = "did not appear verbatim" if found == 0 else f"appears {found} times"
            return f"Error: no replacement was performed: old_str {where} in {path}."
        await box.write_file(path, text.replace(old, new, 1), user=AGENT_USER)
        return f"The file {path} has been edited."

    async def _listing(self) -> str:
        prune = [arg for d in sorted(IGNORED_DIRS) for arg in ("-name", d, "-o")][:-1]
        result = await self._boxes["default"].exec(
            ["find", ".", "(", *prune, ")", "-prune", "-o", "-type", "f", "-print"],
            user=AGENT_USER,
        )
        files = sorted(p.removeprefix("./") for p in result.stdout.splitlines())
        return "\n".join(p for p in files if not is_ignored(p))


def run_episode(env: Env, task_id: str, policy: Policy, seed: int | None = None) -> Episode:
    """Play one episode: the policy gets each observation and returns the next action."""
    episode = Episode(task_id, seed)
    observation = env.reset(task_id, seed)
    episode.observations.append(observation)
    while True:
        action = policy(observation)
        episode.actions.append(action)
        result = env.step(action)
        observation = result.observation
        episode.observations.append(observation)
        if result.done:
            episode.reward, episode.flags = result.reward, result.flags
            return episode


def _absolute(path: str) -> str:
    return path if posixpath.isabs(path) else posixpath.join(REPO_DIR, path)


def _truncate(output: str) -> str:
    data = output.encode()
    if len(data) <= MAX_OUTPUT_BYTES:
        return output
    kept = data[:MAX_OUTPUT_BYTES].decode(errors="ignore")
    return f"{kept}\n[output truncated to {MAX_OUTPUT_BYTES} bytes]"
