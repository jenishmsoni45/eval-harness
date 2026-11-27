# Postmortem: test results forged by the code under test

A grading bug found during the build, in the Phase 4 self-review, before any result was published. Decision D71 records the options and the fix; this note tells the story. Chosen as the postmortem's subject in D83.

## Summary

The scorer trusted the test process to report its own result. But the agent's code runs inside that process, so the agent's code could write the result itself. A change that left the bug in place, ended the test run early with a success exit code and first produced what the scorer reads as a full pass earned full reward with no flag in Python. The same trick made every bug test count as passed in Go and in Rust. A skip raised from the source code on the input the bug gets wrong also counted as a passing bug test. The fix is a finish hook that only the scorer adds: a run counts only if the hook proves the test runner really reached its end.

## Impact

- **E8 did not hold.** "The reward never exceeds the hidden-test pass fraction" held only for results the test runner really produced. A forged run could reach the top reward while no hidden test passed.
- **No flag fired.** The forgery touched no protected path, used none of the runner-detection patterns and ran no snooping command, so the integrity checks saw an honest fix.
- **The RL reward was gameable.** An RL policy is optimised against exactly this reward, so a forgery is the kind of shortcut training would find. The environment uses the same scorer, so it had the same hole.
- **No published number was affected.** It was found before the full run, and the full run's agents never forge results.

## How it was found

The Phase 4 self-review asked, for every value the scorer reads, who produces it. Most inputs were safe: the agent's changes are diffed against a pristine snapshot, protected files are dropped before scoring, and the hidden tests reach only a fresh scoring container. But the verdict itself came from three things written by the test process: its exit code, its JUnit report (Python), and its printed summary lines (`--- PASS` in Go, `test result: ok` in Rust). The agent's code is imported or linked into that very process.

So the review wrote the attack as a test before writing any fix. Each forgery leaves the bug in place and, when the test process starts, writes a passing report or summary and exits with code zero. Played against the real scorer, each one earned what a real fix earns. That test, `tests/adversarial/test_forged_results.py`, was the reproduction.

## Root cause

The scoring design (design §3) separated the agent from the hidden tests: different containers, tests copied in only at scoring time. It did not separate the code under test from the test runner, which is impossible without reworking every task, because the runner has to import or link the code it tests. The scorer then treated the runner's output as trusted. The assumption "the runner's report is the runner's" was never written down, so no invariant test exercised it.

## The fix (D71)

A scorer-only finish hook, added to the scoring container for each attempt, after the visible tests have run and never in the agent's container. It prints a random token only once the runner has finished:

- **Python:** a pytest plugin outside the repo, which also reports how many tests passed and how many were skipped, so a skip raised from source is not a pass.
- **Go:** a `TestMain` in each tested package, which prints the token when `m.Run` returns success.
- **Rust:** libtest has no end-of-run hook, so each test target gets one extra test that sorts last, and the target runs on one thread. Code that exits early never reaches it.

A bug-test or regression run passes only if the token appears, once per test binary, on top of the earlier checks. The token is new for every attempt (`harness/finish_hook.py`).

Options rejected: separating the test process from the code under test (the real fix, but it means reworking every task), detection rules alone (easy to evade, since a forgery can be written many ways), and documenting the hole without closing it.

## Verification

- `tests/adversarial/test_forged_results.py`: a forgery in each language and a skip raised from source each earn nothing, and the real fix on the same tasks still scores in full. Each of these attacks succeeded before the hook.
- The oracle replay of every task's reference fix through the real scorer, hook included, still scores in full, so the hook adds no false failures.
- E8's property tests (`tests/invariants/test_e8_reward.py`) and the RL environment's reward-equality test cover the reward function the hook feeds.

## What remains

The hook shares a machine and a user with the code under test. Code that deliberately searches for the token, in the hook's file or in its own test binary, can still forge a run. Design §5 lists this as a known limit. Closing it means running the tests in a process the code under test cannot reach, which is the rejected rework above and a follow-up.

## Lessons

- **List what the grader trusts, and who writes it.** Every input the scorer reads should have an owner. If the owner is the code being graded, it is an attack surface.
- **Write the exploit as a test first.** The forgery test reproduced the bug, proved the fix, and now guards against regressions.
- **State the limit next to the guarantee.** Design §5 now says the reward property holds for results the runner really produced, and names the case it does not cover.
