"""`make demo` (phases.md P6-3, D86): it runs an honest and a cheating episode, and the
cheater's reward is at most 0."""

from __future__ import annotations

import pytest

from harness.agents import demo_episode
from harness.agents.honest import DEFAULT_MASTER_SEED
from harness.agents.outcomes import attempt_seed
from rl.env import Create, Replace, Run, Submit, View


def test_every_action_has_a_line() -> None:
    lines = [
        demo_episode.describe(a)
        for a in (Run("ls"), View("a"), Create("b", ""), Replace("c", "x", "y"), Submit())
    ]
    assert lines == ["run: ls", "view: a", "create: b", "replace in: c", "submit"]


@pytest.mark.docker
def test_the_demo_runs_both_episodes_and_the_cheater_earns_at_most_zero(
    docker_engine: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert demo_episode.main([]) == 0
    out = capsys.readouterr().out
    honest, cheating = out.split("== edit-test")
    assert honest.startswith(f"== strong (seed {demo_episode_seed()}")
    assert "reward " in honest
    cheater_reward = float(cheating.split("reward ", 1)[1].split(",", 1)[0])
    assert cheater_reward <= 0
    assert "flags: protected_path" in cheating
    assert "the cheater's reward is at most 0" in out


def demo_episode_seed() -> int:
    return attempt_seed(
        DEFAULT_MASTER_SEED, demo_episode.DEFAULT_AGENT, demo_episode.DEFAULT_TASK, 1
    )
