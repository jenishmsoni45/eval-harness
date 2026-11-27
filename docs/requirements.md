# Requirements

What the eval harness must do, for whom, and how each requirement is checked. Decisions referenced as `D<n>` are in [`decisions.md`](decisions.md); invariants `E1`–`E8` are specified in [`design.md`](design.md).

## Purpose

Measure coding agents on realistic bug-fixing tasks and report results a skeptical reviewer can trust: tasks that are provably valid, a sandbox the agent cannot see out of, grading that catches reward hacking, and statistics with honest intervals. The same tasks are exposed as RL environments. No AI model runs anywhere: the agents are scripted programs with known success rates, which is what lets the harness prove it measures correctly. A real model can replace them later by changing one setting.

## Users

| User | Wants | Trusts the harness when |
|---|---|---|
| **Researcher** comparing agents | Run several agents on the task bank and learn which is better and by how much | Intervals cover known true rates, and comparisons only claim a winner when the evidence supports it |
| **RL engineer** | Use the tasks as environments with `reset`, `step` and a reward | The reward cannot be raised by touching tests or other cheats, and episodes start clean |
| **Reviewer** who must trust the numbers | Check that every number is real, every task is valid, and nothing leaked | Every claim traces to a test, a script and a committed log |

## User stories and acceptance criteria

Each acceptance criterion is testable; the phase that delivers it is in [`phases.md`](phases.md).

### Researcher

**R1. Estimate, then run.** As a researcher, I want to see what a full run will cost before starting it, then run every agent on every task with one command.
- `make estimate` prints the number of attempts, the number of containers at once, and the expected wall time, using the limits of D21.
- `make eval` runs the scripted agents and cheaters on every validated task and writes Inspect logs to `results/logs/`.
- A full run fits in 6 hours of wall time (D22); `make estimate` shows this before the run is proposed.

**R2. Pass rates with intervals.** As a researcher, I want pass@1 for each agent with a 95% confidence interval, and pass@k for k from 1 to the number of attempts per task.
- `make report` builds every figure from saved logs only, with no network and no rerun.
- Intervals come from a bootstrap over tasks that keeps each task's attempts together (D7), with a fixed seed, so rebuilding the report from the same logs gives identical output.
- The report breaks results down by difficulty level and by source language.

**R3. Paired comparison.** As a researcher, I want the difference between two agents on the same tasks, with its interval.
- The report shows the paired difference in pass@1 and its 95% interval for each pair of agents.
- The report claims that one agent beats another only when the paired interval excludes zero; otherwise it says the data cannot tell them apart.

**R4. Swap in a real model later.** As a researcher, I want to replace a scripted agent with a real model by changing one setting.
- The Inspect task takes the model as a parameter; scripted agents and cheaters live only in `harness/agents/`.
- A test checks that the task, scorer, integrity, sandbox and statistics modules import nothing from `harness/agents/`.

**R5. Trajectories.** As a researcher, I want to see what the agent did in every attempt.
- Every tool call, its arguments and its output are in the Inspect log (D17).
- Each attempt's record includes the number of tool calls, the wall time, which limit was hit if any, the reward, the integrity flags, and whether it was retried for an infrastructure failure.

### RL engineer

**R6. Environment interface.** As an RL engineer, I want `reset`, `step` and a reward for any validated task.
- `reset(task_id, seed)` starts a clean sandbox and returns the instructions and a listing of the repo.
- `step(action)` takes one tool action (run a command, view a file, create a file, replace a string, submit) and returns the observation and whether the episode is done.
- The reward is returned only when the episode ends, by submit or by reaching a limit, and it is computed by the same scoring code as the eval (D11, D28).
- No observation contains hidden-test names, content or output; the final observation carries only the reward and the flags.
- `close()` removes every container of the episode, and a test checks that none remain.

**R7. A reward that can't be gamed by cheating.** As an RL engineer, I want a reward that never rewards touching tests or other cheats.
- E8 holds: the reward never exceeds the fraction of hidden tests passing, and for the same test results an attempt with any cheat flag always scores lower than one without.
- Doing nothing scores 0; any cheat scores at most 0 (D11, D28).

**R8. Clean, reproducible episodes.** As an RL engineer, I want every episode to start from the same clean state.
- E4 holds for RL episodes as well as eval attempts.
- A scripted policy with the same seed produces the same trajectory and reward.

### Reviewer

**R9. Valid tasks.** As a reviewer, I want proof that every task is fair and not flaky.
- E1 holds: every task passes `make validate` before it is used, with N = 5 runs (D12); any inconsistent result rejects the task.
- Every rule in [`task-spec.md`](task-spec.md) "Validation rules" is checked by the validator, not by hand, except where the spec marks a rule as checked in review.

**R10. No leaks and no network.** As a reviewer, I want proof that the agent cannot see hidden tests or the fix, and cannot reach the network.
- E2 holds: a probe inside the sandbox tries DNS and HTTP and both fail.
- E3 holds: a snooping agent searches the filesystem, git data and environment and finds nothing; image builds never contain hidden material (D26).

**R11. Cheaters are caught.** As a reviewer, I want proof that the integrity checks work.
- E5 holds: every attempt of every scripted cheater (D13) is flagged; no reference fix and no honest scripted agent's attempt gets a cheat flag.

**R12. Correct statistics.** As a reviewer, I want proof that the statistics code is right.
- E7 holds: pass@k matches brute-force enumeration on small cases; bootstrap coverage measured in simulation is within the band set in `design.md`.
- The report shows, for each scripted agent, its true rate on the bank and whether the measured interval covers it.

**R13. Traceable numbers.** As a reviewer, I want every published number to come from a script and a committed log.
- `make report` regenerates every number in `README.md` from the committed logs of the full run (D19).
- No number appears in `README.md` or `docs/` unless a script in the repo produced it.

**R14. Infrastructure failures are not agent failures.** As a reviewer, I want broken containers to never count against an agent.
- E6 holds: infrastructure failures are retried up to 2 times with the same seed; attempts that still fail are excluded and reported; a run with more than 5% excluded is marked invalid (D18).

## Non-functional requirements

| Area | Requirement | Source |
|---|---|---|
| Run time | Full scripted run ≤ 6 hours wall time; `make estimate` checks it first | D22 |
| Per-container limits | 1 CPU, 2 GB memory, ≤ 256 processes | D21 |
| Per-attempt limits | Agent phase ≤ 10 minutes and ≤ 30 tool calls; scoring phase ≤ 5 minutes | D21, D27 |
| Concurrency | 3 attempts at once, within Docker Desktop's cap | D20, D21 |
| Sandbox isolation | `network_mode: none` on every service; non-root user; all capabilities dropped; `no-new-privileges`; no Docker socket; no host mounts | D21, D27 |
| Cleanup | No `evalh-*` or `inspect-evalh-*` container remains after any command | D25 |
| Host safety | Nothing is downloaded except pinned uv packages, digest-pinned official images, hash-locked installs inside an image while it builds, `make audit`'s lookup and read-only `gh` calls; once images are built, every run works with no internet; no container, process or volume outlives its command; nothing is installed on the Mac | D39 |
| Validation | N = 5 runs per check; any flake rejects the task | D12 |
| Retries | ≤ 2 retries per attempt with the same seed; > 5% excluded attempts makes a run invalid | D18 |
| Statistical power | ≥ 80% power to separate the strong and mid agents at 20 tasks × 6 attempts, confirmed by `scripts/power_estimate.py` | D6, D8, D30 |
| Reproducibility | Same code, seeds and logs give an identical report; every random draw is seeded | D5, D7 |
| Dependencies | Well-known packages and official images only, pinned to exact versions (`uv.lock`, image digests); `make audit` passes | D39 |
| Portability | Images build and run on arm64 (this Mac) and amd64 (CI) | D20 |
| CI budget | Pull-request CI validates only the tasks a PR changes; a manual workflow validates all | D15 |
| Cost | Free: no AI model, API key, paid service or cloud account | Non-goals |

## Non-goals

- Running, downloading or calling any AI model, local or hosted.
- Claims about what real models can do.
- Training a model, GPU tasks.
- A web dashboard.
- A custom orchestrator or container runtime; Inspect and Docker do this.
- Tasks from project 1 (tally) (D1).
- Contributing to Inspect upstream from this repo; any contribution is prepared in the owner's fork and submitted by the owner (D16).
