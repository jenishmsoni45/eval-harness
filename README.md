# Agent-evaluation harness and RL environments

Coding tasks made from bugs planted in real projects, run in locked-down Docker sandboxes, graded by hidden tests, checked for reward hacking, and reported with bootstrap confidence intervals. The same tasks are exposed as RL environments.

No AI model runs anywhere. The agents under test are scripted programs with known success rates, plus scripted cheaters, driven through [Inspect](https://inspect.aisi.org.uk/)'s `mockllm` provider, so a real model can replace them by changing one setting. Because each scripted agent's true success rate is known, the report can show that the harness measures correctly: whether each confidence interval covers the true rate, and whether the paired comparison separates agents whose rates really differ.

## Results

<!-- report:start -->

Written by `make report` from the full scripted run's logs in `results/logs/`; the [full report](results/reports/report.md) has every breakdown.

- **Tasks:** 20 validated tasks: 7 easy, 7 medium, 6 hard; 10 Python, 5 Go, 5 Rust.
- **Run:** 467 attempts planned and 467 logged; 0 excluded after infrastructure failures (0.000); 1 retried and then scored; total run time 1 h 00 min.

| Agent | pass@1 | 95% interval | Bank rate | Interval covers it | Population rate | Interval covers it |
|---|---|---|---|---|---|---|
| strong | 0.700 | [0.575, 0.817] | 0.690 | yes | 0.698 | yes |
| mid | 0.558 | [0.442, 0.675] | 0.517 | yes | 0.526 | yes |
| weak | 0.267 | [0.175, 0.367] | 0.298 | yes | 0.305 | yes |

- **strong vs mid** (primary): difference 0.142, 95% interval [0.058, 0.233]: strong beats mid.
- **strong vs weak** (secondary): difference 0.433, 95% interval [0.325, 0.533]: strong beats weak.
- **mid vs weak** (secondary): difference 0.292, 95% interval [0.200, 0.375]: mid beats weak.
- **Integrity:** 107 of 107 scripted cheater attempts were flagged; 0 of 360 honest attempts got a cheat flag; 118 of 301 honest apparent passes carry the overfitting signal (visible tests pass, hidden tests do not).
- **Per attempt:** median 5.000 tool calls and median 15.903 seconds of wall time.

<!-- report:end -->

Every number above is written by `make report` from the committed logs of the full scripted run, and a test fails if this block differs from a fresh build. The numbers describe scripted agents, so they show how well the harness measures, not how well any model codes.

## What it does

- **Tasks** (`task_bank/`): each task is a snapshot of one of my Python, Go or Rust projects with one planted bug, an issue-style report of the symptom, visible tests, hidden tests and a reference fix. `make validate` checks every task: the shipped bug fails the hidden tests, and the reference fix passes them on every run ([task spec](docs/task-spec.md)).
- **Sandbox** (`harness/sandbox/compose.yaml`): no network, a non-root user, every capability dropped, CPU, memory and process limits, and a fresh pair of containers for every attempt, built from an image whose git history is stripped. Hidden tests reach only a separate scoring container, and only at scoring time.
- **Scoring** (`harness/scorer.py`): the agent's changes are compared with the snapshot. Changes to tests or test configuration are dropped and flagged. The hidden bug tests give partial credit only when the regression suite passes, and any cheat flag costs a full point, so cheating never beats doing nothing ([design](docs/design.md), D11, D28).
- **Integrity** (`harness/integrity.py`): protected paths, runner detection and snooping rules, and the overfitting signal (visible tests pass, hidden tests do not). Scripted cheaters prove that each rule fires.
- **Statistics** (`stats/`): pass@k with the unbiased estimator, a cluster bootstrap over tasks, paired differences, and a calibration check against the scripted agents' true rates.
- **RL environment** (`rl/env.py`): `reset`, `step` and `close` over the same images, limits and scorer as the eval.

## Quick start

It needs Docker Desktop, uv and git, and the Python version pinned in `pyproject.toml`. Nothing else is installed, and once the images are built everything runs offline.

```sh
uv sync --frozen
make lint test audit   # static checks, the tests, and pip-audit on the locked dependencies
make validate          # build every task image and validate every task (slow)
make estimate          # attempts, containers at once and expected wall time of the full run
make eval              # the full scripted run (long: run make estimate first)
make report            # rebuild the report and this README's results from the logs
make demo              # two RL episodes on one task: an honest agent and a cheater
```

## RL environment

```python
from rl.env import Env, Run, Submit, View

with Env() as env:
    observation = env.reset("risk-002", seed=7)  # the instructions and a listing of the repo
    env.step(Run("cd /work/repo && python -m pytest -q tests/visible"))
    env.step(View("/work/repo/ml/threshold.py"))
    # ... Replace(path, old_str, new_str) or Create(path, file_text) to change files ...
    result = env.step(Submit())
    print(result.reward, result.flags)
```

An action is `Run`, `View`, `Create`, `Replace` or `Submit`, as the eval agent's `bash` and `text_editor` tools. The episode ends on submit or at the eval's step and time limits. The reward comes only at the end, from the eval's own scorer, and the final observation carries only the reward and the flags: no observation ever contains a hidden test's name, content or output. Every episode starts from the pristine image, and its containers are removed when it ends.

The scripted agents and cheaters also run as policies (`harness.agents.rl_policy.scripted_policy`). An honest agent with a given seed plays exactly the eval's attempt with that seed, and `tests/unit/test_rl_env.py` checks that the episode's reward equals the eval scorer's for the same changes.

## Guarantees

| | Invariant | Test |
|---|---|---|
| E1 | Every task is valid: the bug fails the hidden tests, and the reference fix passes them on every run | `tests/invariants/test_e1_validity.py`, `make validate` |
| E2 | The sandbox has no network access | `tests/invariants/test_e2_network.py` |
| E3 | The agent never sees hidden tests or the fix: not in the filesystem, git history, environment or image layers | `tests/invariants/test_e3_leakage.py` |
| E4 | Every attempt starts from a clean filesystem | `tests/invariants/test_e4_clean_fs.py` |
| E5 | Every scripted cheater is flagged, and no reference fix is | `tests/cheaters/`, `tests/invariants/test_e5_no_false_flags.py` |
| E6 | Infrastructure failures are retried and never counted as agent failures | `tests/invariants/test_e6_infra.py` |
| E7 | pass@k and the bootstrap match brute force and simulation | `tests/invariants/test_e7_stats.py` |
| E8 | The reward never exceeds the hidden-test pass fraction, and touching protected paths always lowers it | `tests/invariants/test_e8_reward.py` |

## Known limits

- The agents are scripted, so the results say nothing about any real model; they show that the harness measures what it claims to.
- Code under test can still forge a test run if it deliberately finds the scorer's finish token, because both share a machine and a user ([postmortem](docs/postmortem.md), D71).
- Runner detection and snooping are pattern lists, so an obfuscated variant can evade them ([design](docs/design.md)).
- The Docker tests ran locally on `arm64` only. They have not run on `amd64` in CI (D72, D75, D87).

## Engineering approach

- **Design before code.** I wrote the requirements, architecture, design, task spec and phase plan before writing any code. Every design question, the options I weighed and the choice I made are recorded in [docs/decisions.md](docs/decisions.md).
- **One phase, one pull request.** Each phase has testable acceptance criteria. Each pull request maps every criterion to the code and the test that proves it, and includes a self-review of the full diff.
- **Local, pinned and clean.** Dependencies are pinned in the lockfile and the base images by digest, and `make audit` checks the locked versions for known vulnerabilities. Once the images are built, everything runs offline. Nothing is installed on the host, and every container is named `evalh-*` and removed when its command ends.
- **Verification.** The invariants are tests. Every task passes validation before it is used. Scripted agents with known rates check the statistics end to end, and every published number is rebuilt from committed logs. Adversarial tests and self-reviews caught real bugs before they could affect a result, among them test results forged by the code under test ([postmortem](docs/postmortem.md), D71) and a fault-injection test that passed by accident (D79).

## Documentation

[Requirements](docs/requirements.md) · [Architecture](docs/architecture.md) · [Design](docs/design.md) · [Task spec](docs/task-spec.md) · [Decisions](docs/decisions.md) · [Phases](docs/phases.md) · [Postmortem](docs/postmortem.md) · [Talk outline](docs/talk-outline.md)
