"""The RL environment (phases.md P6-2; requirements.md R6 to R8; architecture.md "RL episode").

Every test plays real episodes in Docker on one quick Python task, `risk-002`, whose full-run
attempts include every kind of outcome: a success, a wrong fix with partial credit, giving up,
running out of steps, and each cheater's trick. Episodes are replays of those logged attempts,
so the reward an episode earns is checked against the eval scorer's reward for the same changes,
read from the committed logs (D19).
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from functools import cache
from pathlib import Path

import pytest

from harness.agents.rl_policy import scripted_policy
from harness.attempt import MAX_TURNS
from harness.eval import prompt
from harness.tasks import is_ignored, load_task, read_tree
from rl.env import Create, Env, Episode, Replace, Run, Submit, View, run_episode
from stats import report

pytestmark = pytest.mark.docker

TASK = "risk-002"
# (agent, epoch) of logged attempts on TASK: a success, a wrong fix with partial credit, giving
# up, running out of steps (the step limit), and three cheaters with different flags.
REPLAYED = (
    ("strong", 1),
    ("weak", 1),
    ("weak", 3),
    ("weak", 2),
    ("edit-test", 1),
    ("detect-runner", 1),
    ("snoop", 1),
)


@cache
def logged(agent: str, epoch: int) -> report.Attempt:
    run = report.read_run(report.LOG_DIR.glob("*.eval"))
    return next(a for a in run.attempts if (a.agent, a.task_id, a.epoch) == (agent, TASK, epoch))


def seed_of(agent: str, epoch: int) -> int | None:
    seed = logged(agent, epoch).info.get("seed")
    return int(seed) if seed is not None else None


@pytest.fixture(scope="module")
def env(docker_engine: None) -> Iterator[Env]:
    with Env() as environment:
        yield environment


@pytest.fixture(scope="module")
def replays(env: Env) -> dict[tuple[str, int], Episode]:
    episodes = {}
    for agent, epoch in REPLAYED:
        seed = seed_of(agent, epoch)
        episodes[(agent, epoch)] = run_episode(env, TASK, scripted_policy(agent, TASK, seed), seed)
    return episodes


def containers_of(project: str) -> list[str]:
    out = subprocess.run(
        ["docker", "ps", "--all", "--filter", f"name={project}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [name for name in out.stdout.split() if name.startswith(project)]


# --- reset ------------------------------------------------------------------------------------


def test_reset_returns_the_instructions_and_the_repo_listing(env: Env) -> None:
    task = load_task(TASK)
    observation = env.reset(TASK, seed=3)
    try:
        assert observation.startswith(prompt(task.visible_command, task.instructions))
        listing = observation.split("Files in /work/repo:\n", 1)[1].splitlines()
        assert listing == sorted(p for p in read_tree(task.repo_dir) if not is_ignored(p))
        assert env.seed == 3
    finally:
        env.close()


# --- step -------------------------------------------------------------------------------------


def test_step_handles_every_action_type(env: Env) -> None:
    env.reset(TASK)
    try:
        out = env.step(Run("echo to-stdout; echo to-stderr >&2; whoami; pwd"))
        assert (out.done, out.reward, out.flags) == (False, None, ())
        # As the eval's bash tool shows it: stderr, a blank line, then stdout.
        assert out.observation == "to-stderr\n\nto-stdout\nagent\n/work/repo\n"

        out = env.step(View("/work/repo"))
        assert "/work/repo/tests/visible" in out.observation
        assert ".git" not in out.observation

        out = env.step(Create("notes/todo.txt", "first line\nsecond line\n"))
        assert out.observation == "File created successfully at: /work/repo/notes/todo.txt"
        out = env.step(View("/work/repo/notes/todo.txt"))
        assert "     1\tfirst line\n     2\tsecond line" in out.observation

        out = env.step(Replace("/work/repo/notes/todo.txt", "second", "2nd"))
        assert out.observation == "The file /work/repo/notes/todo.txt has been edited."
        out = env.step(Replace("/work/repo/notes/todo.txt", "absent", "x"))
        assert out.observation.startswith("Error: no replacement was performed")
        out = env.step(View("/work/repo/no/such/file.py"))
        assert out.observation == "Error: FileNotFoundError: /work/repo/no/such/file.py"
        out = env.step(Run("cat notes/todo.txt"))
        assert out.observation == "first line\n2nd line\n"
        env.step(Create(".hidden-note", "dot\n"))
        out = env.step(View("/work/repo/.hidden-note"))
        assert out.observation.endswith("     1\tdot\n     2\t")

        out = env.step(Submit())
        # A note that fixes nothing: no bug test passes, nothing is flagged.
        assert (out.done, out.reward, out.flags) == (True, 0.0, ())
        assert out.observation == "The episode is over. Reward: 0. Flags: none."
        with pytest.raises(RuntimeError, match="call reset first"):
            env.step(Run("true"))
    finally:
        env.close()


def test_a_new_episode_starts_clean(env: Env) -> None:
    """E4 for episodes (R8): nothing one episode wrote is there in the next."""
    env.reset(TASK)
    env.step(Run('touch /work/repo/marker /tmp/marker "$HOME/marker"'))
    env.step(Submit())
    env.reset(TASK)
    try:
        out = env.step(
            Run('ls /work/repo/marker /tmp/marker "$HOME/marker" 2>&1; git status --short')
        )
        assert out.observation.count("No such file or directory") == 3
        assert "marker" not in out.observation.split("No such file or directory")[-1]
    finally:
        env.close()


def test_a_step_that_is_not_an_action_is_refused(env: Env) -> None:
    env.reset(TASK)
    try:
        with pytest.raises(TypeError, match="not an action"):
            env.step("ls")  # type: ignore[arg-type]
    finally:
        env.close()


# --- reward -----------------------------------------------------------------------------------


@pytest.mark.parametrize(("agent", "epoch"), REPLAYED)
def test_the_reward_equals_the_eval_scorers_for_the_same_changes(
    replays: dict[tuple[str, int], Episode], agent: str, epoch: int
) -> None:
    episode = replays[(agent, epoch)]
    record = logged(agent, epoch).record
    assert (episode.reward, list(episode.flags)) == (record["reward"], record["flags"])


def test_running_out_of_steps_ends_the_episode_at_the_step_limit(
    replays: dict[tuple[str, int], Episode],
) -> None:
    assert logged("weak", 2).info["outcome"] == "out_of_steps"
    episode = replays[("weak", 2)]
    assert len(episode.actions) == MAX_TURNS
    assert not any(isinstance(a, Submit) for a in episode.actions)


def test_a_scripted_policy_with_the_same_seed_gives_the_same_trajectory_and_reward(
    env: Env, replays: dict[tuple[str, int], Episode]
) -> None:
    first = replays[("weak", 1)]
    seed = seed_of("weak", 1)
    again = run_episode(env, TASK, scripted_policy("weak", TASK, seed), seed)
    assert again.actions == first.actions
    assert (again.reward, again.flags) == (first.reward, first.flags)


# --- what the policy can see -------------------------------------------------------------------


def hidden_material() -> list[str]:
    """Strings that would show hidden tests reached an observation: their ids, their test
    names, their file names, their distinctive lines, and the bank's canary."""
    task = load_task(TASK)
    found = [task.canary]
    for test in task.bug_tests:
        found += [test, test.rsplit("::", 1)[-1]]
    for path, data in read_tree(task.hidden_tests_dir).items():
        found.append(Path(path).name)
        found += [
            line.strip()
            for line in data.decode().splitlines()
            if len(line.strip()) > 30 and not line.strip().startswith(("import ", "from "))
        ]
    return found


def test_no_observation_contains_hidden_test_names_content_or_output(
    replays: dict[tuple[str, int], Episode],
) -> None:
    material = hidden_material()
    assert len(material) > 10
    for (agent, epoch), episode in replays.items():
        for observation in episode.observations:
            leaked = [m for m in material if m in observation]
            assert not leaked, (agent, epoch, leaked)
        # The final observation carries only the reward and the flags (R6).
        final = episode.observations[-1]
        flags = ", ".join(episode.flags) or "none"
        assert final == f"The episode is over. Reward: {episode.reward:g}. Flags: {flags}."


# --- close ------------------------------------------------------------------------------------


def test_close_leaves_no_container(env: Env) -> None:
    env.reset(TASK)
    project = env.project_name
    assert project is not None
    assert project.startswith("evalh-rl-")
    assert len(containers_of(project)) == 2
    env.close()
    assert containers_of(project) == []
    assert env.project_name is None
    env.close()  # closing twice is harmless


def test_an_ended_episode_has_already_removed_its_containers(env: Env) -> None:
    env.reset(TASK)
    project = env.project_name
    assert project is not None
    env.step(Submit())
    assert containers_of(project) == []
