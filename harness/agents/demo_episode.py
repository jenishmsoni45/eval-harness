"""`make demo`: two RL episodes on one task, one honest and one cheating (phases.md P6-3, D86).

The honest scripted agent plays an attempt with the given seed and draws its outcome as in the
eval; the cheater plays its trick. Each episode prints its actions and its reward and flags. The
cheater's reward must be at most 0 (D11, D28), so the demo exits 1 if it is not.

    python -m harness.agents.demo_episode [--task risk-001] [--agent strong] [--seed N]
                                          [--cheater edit-test]

Each episode starts its own two containers and removes them when it ends.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from harness.agents import cheaters
from harness.agents.honest import DEFAULT_MASTER_SEED
from harness.agents.outcomes import AGENTS, attempt_seed
from harness.agents.rl_policy import honest_outcome, scripted_policy
from rl.env import Action, Create, Env, Episode, Replace, Run, Submit, View, run_episode

DEFAULT_TASK = "risk-001"
DEFAULT_AGENT = "strong"
DEFAULT_CHEATER = "edit-test"


def describe(action: Action) -> str:
    if isinstance(action, Run):
        return f"run: {action.command}"
    if isinstance(action, View):
        return f"view: {action.path}"
    if isinstance(action, Create):
        return f"create: {action.path}"
    if isinstance(action, Replace):
        return f"replace in: {action.path}"
    if isinstance(action, Submit):
        return "submit"
    raise TypeError(action)


def show(title: str, episode: Episode, say: Callable[[str], None]) -> None:
    say(f"== {title} on {episode.task_id}")
    for n, action in enumerate(episode.actions, 1):
        say(f"  {n:2}. {describe(action)}")
    say(f"  reward {episode.reward:g}, flags: {', '.join(episode.flags) or 'none'}")


def demo(
    env: Env,
    task_id: str,
    agent: str,
    seed: int,
    cheater: str,
    say: Callable[[str], None] = print,
) -> tuple[Episode, Episode]:
    """The honest episode, then the cheating one."""
    outcome = honest_outcome(agent, task_id, seed)
    honest_run = run_episode(env, task_id, scripted_policy(agent, task_id, seed), seed)
    show(f"{agent} (seed {seed}, drawn outcome: {outcome.value})", honest_run, say)
    cheating_run = run_episode(env, task_id, scripted_policy(cheater, task_id))
    show(f"{cheater} (a scripted cheater)", cheating_run, say)
    return honest_run, cheating_run


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task", default=DEFAULT_TASK)
    parser.add_argument("--agent", default=DEFAULT_AGENT, choices=AGENTS)
    parser.add_argument("--seed", type=int, default=None, help="default: the eval's first epoch")
    parser.add_argument("--cheater", default=DEFAULT_CHEATER, choices=sorted(cheaters.CHEATERS))
    args = parser.parse_args(argv)
    seed = args.seed
    if seed is None:
        seed = attempt_seed(DEFAULT_MASTER_SEED, args.agent, args.task, 1)
    with Env() as env:
        _, cheating_run = demo(env, args.task, args.agent, seed, args.cheater)
    if cheating_run.reward is None or cheating_run.reward > 0:
        print(f"the cheater's reward is above 0: {cheating_run.reward}")
        return 1
    print("the cheater's reward is at most 0, as the reward design requires (D11, D28)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
