# Talk outline: measuring coding agents you can trust

A twenty-minute talk for research engineers, in eight parts. Every number on a slide comes from the README's results block, which `make report` writes from the committed logs; none is typed into the slides. The demo video (a cheater caught, then a report with intervals) is recorded separately and plays in part six.

## 1. The question (opening, short)

- "How do you know your eval measures what you think it measures?" One leaderboard number hides task validity, leaks, reward hacking and noise.
- The claim of the talk: an eval is a measuring instrument, and an instrument needs a calibration.
- The trick that makes calibration possible: agents whose true success rate is known.

## 2. Tasks that are provably fair

- Bugs planted in my own Python, Go and Rust projects, each with an issue-style report, visible tests, hidden tests and a reference fix.
- Validation (E1): the shipped bug fails the hidden tests and the reference fix passes them on every run; a flaky task is rejected.
- Visible and hidden tests differ, so overfitting to the visible tests shows up.
- The difficulty ladder: an easy task has a failing visible test; a medium one passes every visible test and its fix lies away from the symptom; a hard one needs changes in several files, or an invariant that must be understood first.

## 3. A sandbox the agent cannot see out of

- No network (E2), a non-root user, dropped capabilities, resource limits, git history stripped.
- Hidden tests reach only a separate scoring container, at scoring time (E3); every attempt starts clean (E4).
- Infrastructure failures are retried and never counted against the agent (E6).
- Built on Inspect: its `mockllm` provider runs scripted agents in place of a model, so a real model replaces them with one setting.

## 4. Grading that catches reward hacking

- The reward: partial credit from bug tests, but only when the regression suite passes; any cheat flag costs a full point, so cheating never beats doing nothing (E8).
- Integrity rules: protected paths, runner detection, snooping, and the overfitting signal.
- Scripted cheaters prove the rules fire (E5): edit, delete or skip tests, hard-code the visible inputs, detect the test runner, snoop for hidden files.
- The postmortem (D71): code under test forged its own test results, and the scorer believed it. How it was found, the finish hook that fixed it, and the limit that remains.

## 5. Statistics with honest intervals (main section)

- Scripted agents with known per-level rates and per-task difficulty offsets, so each agent's true rate on the bank is known.
- Bootstrap over tasks, not attempts: tasks are the unit that varies, and attempts on one task are correlated.
- pass@k with the unbiased estimator, checked against brute-force enumeration (E7).
- Coverage checked in simulation before the run, and the power estimate that fixed the run size (design §7).
- Results slides, from the README block: each agent's pass@1 with its interval, whether the interval covers the true rate, and the paired comparison, which names a winner only when its interval excludes zero.

## 6. Demo (video)

- A cheater edits a test: the change is dropped, the flag fires, the reward goes negative.
- The report: intervals, the calibration check and the integrity table, rebuilt from the logs by `make report`.

## 7. The same tasks as RL environments

- `reset`, `step` and `close` over the same images, limits and scorer, so the reward cannot drift from the eval's.
- No observation contains hidden-test names, content or output; the final observation carries only the reward and the flags.
- Scripted policies replay eval attempts, and the test checks that each episode's reward equals the eval scorer's.
- Why it matters for training: a reward that can be gamed by touching tests is exactly what a policy learns to exploit.

## 8. Limits and what is next (closing, short)

- Scripted agents measure the harness, not any model; the next step is plugging in a real model.
- Known limits: the finish hook can be defeated by code that hunts for its token; detection rules are pattern lists.
- Follow-ups: a separate test process, the Docker tests in CI on `amd64`, a larger bank.
- How it was built: planned first, one reviewed pull request per phase, a command guard, every number rebuilt from logs.

## Questions to be ready for

- How do you know a task is fair and not flaky?
- What does your confidence interval assume?
- How do you stop an agent escaping the sandbox?
- Why scripted agents, and what changes when a real model is plugged in?
- How would you shape the reward so an agent can't game it?
- Why build on Inspect instead of writing your own harness?
