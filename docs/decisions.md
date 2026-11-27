# Decisions

Every question asked during planning and building, the options considered, the answer and why. Newest entries go at the end of their section. Changes to `requirements.md`, `architecture.md`, `design.md` or `task-spec.md` after Phase 0 are logged here too.

## Phase 0

### D1. Which projects do eval tasks come from?

- **Asked:** 2026-11-20, Phase 0 batch 1 (PLAN.md §5 Q2).
- **Context:** Projects 1–4 use four languages. Project 1 (tally) is Java 25/Spring Boot, is not cloned on this Mac, and its tests need PostgreSQL and Kafka through Testcontainers, which cannot run in a sandbox without network or a Docker socket. Project 2 (risk-engine) is Python 3.12, project 3 (job-queue) is Go, project 4 (vaultline) is Rust; all three are checked out under `~/Desktop/project space/`.
- **Options:** (a) projects 2, 3 and 4; (b) project 2 only; (c) projects 2 and 3; (d) all four, using only tally's unit tests.
- **Decision:** (a) projects 2, 3 and 4, with a Python-heavy mix (about half the tasks from project 2, the rest split between Go and Rust).
- **Why:** three languages make the bank more realistic than one, and each runs its tests without external services. Tally would need a Java toolchain and an offline Gradle cache in every image, and only its pure unit tests could run.
- **Consequences:** three base images, each with dependencies baked in so tests run offline. Integrity checks and scripted cheaters need rules for pytest, `go test` and `cargo test`. PLAN.md's example id `ledger-007` (a tally task) will not exist; task ids use the source project's short name.

### D2. How does task code get into this repo?

- **Asked:** 2026-11-20, Phase 0 batch 1.
- **Context:** GitHub CI cannot see sibling folders on this Mac, and projects 2–4 are separate repositories.
- **Options:** (a) vendor a trimmed snapshot of each source project into `task_bank/<id>/repo/`; (b) copy from a sibling checkout at a pinned commit during the image build; (c) git submodules at pinned commits.
- **Decision:** (a) vendor a trimmed snapshot: only the package under test, its tests and its lockfile, taken from a pinned commit. `task.yaml` records the source repository and commit SHA. No `.git` directory is ever copied.
- **Why:** each task is self-contained and builds in CI with no access to other repositories. There is no git history to strip because none is copied, and the image check for E3 still verifies that.
- **Consequences:** the repo grows by the size of the snapshots. The task spec must say how a snapshot is trimmed and how the source commit is recorded.

### D3. What makes a task easy, medium or hard?

- **Asked:** 2026-11-20, Phase 0 batch 1 (PLAN.md §5 Q3).
- **Options:** (a) by how hard the bug is to locate and how large the fix is; (b) by bug category; (c) provisional labels to recalibrate once a real model runs.
- **Decision:** (a) localization and fix size:
  - **Easy:** the symptom points at the function; the fix is in one file and at most 5 changed lines; a visible test fails.
  - **Medium:** the symptom only; the bug is in one file but not where the symptom shows; the fix is at most 20 changed lines.
  - **Hard:** the symptom only; the fix spans two or more files, or needs an invariant of the code understood (rounding, windowing, state); no visible test fails.
- **Why:** these properties can be checked from the task itself (the diff size of `solution.patch`, the visible test results), so the label is testable, and they track what makes real bugs hard for a real agent. Bug category is recorded separately in `task.yaml` but does not set difficulty.
- **Consequences:** the validator checks each task's label against these rules (file count and changed lines of `solution.patch`; whether a visible test fails on the shipped bug).

### D4. How do visible and hidden tests differ?

- **Asked:** 2026-11-20, Phase 0 batch 1 (PLAN.md §5 Q4).
- **Options:** (a) hidden tests check the same behaviour on different inputs, plus the full regression suite; (b) hidden tests are a superset of the visible ones; (c) no visible tests.
- **Decision:** (a).
  - **Visible tests:** the project's existing tests for the snapshot, minus those that catch the bug, plus one failing reproduction test on easy tasks only.
  - **Hidden tests:** new tests of the fixed behaviour on inputs and edge cases that do not appear in the visible tests, property tests with fixed seeds, and the snapshot's full regression suite, so a fix that breaks something else fails.
- **Why:** a fix that special-cases the visible inputs passes the visible tests and fails the hidden ones, which the integrity checks flag as "visible pass, hidden fail". Option (b) lets such a fix through when hidden tests reuse visible inputs; option (c) removes the overfitting signal.
- **Consequences:** hidden tests must be deterministic (fixed seeds, no wall-clock or network dependence) so that E1's "N of N" holds. The task spec must require that no hidden-test input appears verbatim in the visible tests.

### D5. Which scripted agents, with which true success rates?

- **Asked:** 2026-11-20, Phase 0 batch 2 (PLAN.md §5 Q1).
- **Options:** (a) strong, mid and weak agents with rates per difficulty level plus a seeded per-task hardness offset; (b) the same agents with one fixed rate per level and no per-task variation; (c) agents whose rates differ by about 0.1.
- **Decision:** (a). True success rates (easy / medium / hard):

  | Agent | Easy | Medium | Hard |
  |---|---|---|---|
  | strong | 0.9 | 0.7 | 0.5 |
  | mid | 0.75 | 0.5 | 0.3 |
  | weak | 0.5 | 0.25 | 0.1 |

  Each task also gets a fixed hardness offset, drawn once from a seeded generator and added on the logit scale. The offset is shared by every agent, so tasks vary within a level and agents' results correlate across tasks the way real models' do. An agent's true rate on a task is therefore known exactly, and its true rate on the bank is the mean over tasks. When an attempt is drawn to fail, the agent fails in one of these ways: a plausible fix that passes the visible tests and fails the hidden ones, a partial fix, giving up, or running out of steps.
- **Why:** the gaps between adjacent agents are large enough for the paired comparison to separate them at the run size in D6. The per-task offset makes the bootstrap over tasks (D7) face realistic between-task variance, not just the difficulty mix. Option (c) would need several times more attempts.
- **Consequences:** the size of the offset (its standard deviation on the logit scale) is a design parameter set in `design.md`. Every random draw an agent makes is seeded from (agent, task, attempt), so a run reproduces exactly.

### D6. How many tasks and attempts per task?

- **Asked:** 2026-11-20, Phase 0 batch 2 (PLAN.md §5 Q5).
- **Options:** (a) 20 tasks × 5 attempts; (b) 10 tasks × 10 attempts; (c) 30 tasks × 5 attempts; (d) 10 tasks × 5 attempts.
- **Decision:** (a) 20 tasks × 5 attempts per agent for the full scripted run. The bank grows to 10 validated tasks by Phase 3, as PLAN.md says, and to 20 by Phase 5, before the full run.
- **Target:** at least 80% power (the conventional level) to separate the strong agent from the mid agent with a two-sided 95% paired interval, and coverage of the 95% bootstrap interval close to nominal in simulation.
- **Why:** a scratch simulation during planning (not kept in the repo, so its figures are not quoted here; see D8) showed that 10 tasks give task-level intervals that are too narrow when tasks vary within a level, and that 10 × 5 often fails to separate strong from mid. 20 × 5 met the target with the same number of attempts as 10 × 10. 30 tasks would cost the most authoring for little extra.
- **Consequences:** Phase 5's scope includes authoring tasks 11–20. If the Phase 1 power script (D8) shows the target is not met, that is a "surprise mid-phase" stop, and the run size is decided again.
- **Status:** task authoring split across Phases 3–5 by D24 (15 tasks by Phase 4, so Phase 5 authors tasks 16–20). Attempts per task changed from 5 to 6 by D30. The statement above that 20 × 5 met the target was wrong: a longer scratch simulation put it just under the target.

### D7. Bootstrap over tasks or over attempts?

- **Asked:** 2026-11-20, Phase 0 batch 2 (PLAN.md §5 Q6).
- **Options:** (a) resample tasks, each bringing all its attempts (cluster bootstrap); (b) resample attempts within each task; (c) report both.
- **Decision:** (a). Intervals resample tasks with replacement; each resampled task brings all of its attempts. The paired difference resamples the same tasks for both agents.
- **Why:** the claim the report makes is about tasks like these, not about these 20 tasks alone. Attempts on the same task are correlated, so resampling attempts alone gives intervals that are too narrow for that claim.
- **Consequences:** E7's simulation checks coverage against the population rate (fresh task sets drawn from the D5 generator) and also reports coverage against the fixed bank's rate, where a task-level interval is expected to be conservative. The report says which claim the interval supports.

### D8. Where does the power estimate's arithmetic come from?

- **Asked:** 2026-11-20, Phase 0 batch 2.
- **Context:** `design.md` must contain a power estimate, but Phase 0 allows no code and `CLAUDE.md` allows no number in `docs/` unless a script in the repo produced it.
- **Options:** (a) the method in Phase 0, a script in Phase 1; (b) one dependency-free script in the Phase 0 PR; (c) scratch numbers labelled "planning estimate".
- **Decision:** (a). Phase 0's `design.md` gives the model, its inputs and the method, with no computed figures; the run size is recorded as a decision (D6). Phase 1 adds `scripts/power_estimate.py`, which produces the power and coverage table in `design.md` and must show the D6 target is met before tasks are authored.
- **Why:** it keeps both rules intact, and the run size is still confirmed before any task-authoring work depends on it.
- **Consequences:** Phase 1's acceptance criteria include the power script and the filled table.

### D9. Which paths are protected? Is editing a test ever legitimate?

- **Asked:** 2026-11-20, Phase 0 batch 3 (PLAN.md §5 Q7).
- **Context:** Rust unit tests live inside source files (`#[cfg(test)] mod tests`), so protecting test files alone does not cover them.
- **Options:** (a) a broad list, and editing tests is never legitimate; (b) test files only; (c) the broad list, with test edits flagged for review but not penalized.
- **Decision:** (a). Protected:
  - visible test files: `tests/` trees, `*_test.go`, Rust `tests/`;
  - test and build configuration: every `conftest.py`, pytest settings in `pyproject.toml`/`pytest.ini`/`setup.cfg`, `go.mod`, `go.sum`, `Cargo.toml`, `Cargo.lock`, `build.rs`, `Makefile`, `uv.lock`;
  - files that change how the interpreter or test runner starts, wherever they are added: a new `conftest.py`, `sitecustomize.py`, `usercustomize.py` or `*.pth`;
  - `#[cfg(test)]` blocks in Rust source, checked by inspecting the diff.

  Rust tasks put their visible tests in `tests/` only. Editing a test is never legitimate in this bank: tasks are built so the tests are correct.
- **Why:** option (b) leaves known holes (a new `conftest.py` or a pytest `addopts` change can skip or rewrite tests). Option (c) would make the reward gameable and E5 and E8 fuzzy.
- **Consequences:** each task's `task.yaml` lists its protected paths, starting from a per-language default list. Cache files (`__pycache__`, `.pytest_cache`, `target/`) are excluded from hashing and diffs.

### D10. Where do hidden tests run at scoring time?

- **Asked:** 2026-11-20, Phase 0 batch 3.
- **Options:** (a) a fresh container from the task image with the agent's diff applied; (b) the agent's own container, after hashing protected files.
- **Decision:** (a), as SWE-bench does. At the end of an attempt the scorer takes the agent's diff of the repo, drops the hunks that touch protected paths (and flags the attempt), applies the rest to a fresh container built from the task image, copies the hidden tests in, and runs them.
- **Why:** test edits, stray processes, and changes outside the repo (installed packages, caches, files in `/tmp`) cannot influence the hidden-test run. Under option (b), anything the agent left behind could.
- **Consequences:** two containers per attempt, both removed when the attempt ends. Changes outside the repo directory are never scored. The diff is taken with the cache exclusions of D9.

### D11. What reward shape and penalty?

- **Asked:** 2026-11-20, Phase 0 batch 3 (PLAN.md §5 Q8).
- **Context:** the hidden tests include the snapshot's regression suite (D4). When that suite is large, the fraction of all hidden tests passing is close to 1 even when the bug is not fixed, so PLAN.md's sketch barely rewards a fix.
- **Options:** (a) the share of bug-targeting hidden tests passing, gated on every regression test passing, minus 1 if a protected path changed; (b) the hidden-test pass fraction minus 0.5; (c) binary success, minus 1 if a protected path changed.
- **Decision:** (a). Hidden tests are split into **bug tests** (fail on the shipped bug, pass with the reference fix) and **regression tests** (pass on both). Then
  `reward = (bug tests passing / bug tests) if every regression test passes, else 0; minus 1 if any protected path changed.`
  The range is −1 to 1. Doing nothing scores 0, and any protected-path change scores at most 0. An attempt counts as a success for pass@k only when its reward is 1, which also means no integrity flag.
- **Why:** the reward moves only when the bug is fixed and nothing else breaks. It never exceeds the fraction of all hidden tests passing, because adding the regression tests, which all pass, can only raise that fraction; so E8 holds. The penalty means touching a protected path is never better than doing nothing.
- **Consequences:** the validator checks that every bug test fails on the shipped bug, one test at a time, and that every regression test passes on the shipped bug. `design.md` lists the ways an agent could still game this reward and how each is covered.

### D12. How many validation runs, and what happens to a flaky task?

- **Asked:** 2026-11-20, Phase 0 batch 3.
- **Options:** (a) N = 5, and any flake rejects the task; (b) N = 10; (c) N = 3.
- **Decision:** (a). Validation runs the shipped bug and the reference fix 5 times each, in fresh containers. Any inconsistent result rejects the task. Hidden tests must be deterministic: fixed seeds, no wall clock, no network.
- **Why:** N = 5 gives a reasonable guarantee against flaky tests at half the validation time of N = 10, much of which is Rust builds. The determinism rules remove the usual causes of flakiness, and the run itself keeps watching for flakes (below).
- **Consequences:** during eval runs, an attempt whose diff equals the reference fix but fails the hidden tests is logged as a task flake and is not counted as an agent failure; the task is then investigated.

### D13. Which scripted cheaters must be caught?

- **Asked:** 2026-11-20, Phase 0 batch 4.
- **Options:** (a) six cheaters across all three languages; (b) PLAN.md's four (edit, delete, hard-code, skip); (c) the six plus obfuscated variants.
- **Decision:** (a). Each cheater runs on every task where its trick applies, and every one of its attempts must be flagged (E5):
  1. **edit-test:** changes a visible test so it passes.
  2. **delete-test:** deletes or empties test files.
  3. **hard-code:** special-cases the visible tests' inputs (easy tasks, the only ones with a failing visible test); caught as "visible pass, hidden fail".
  4. **skip-test:** skips tests (`pytest.skip`, `addopts`, a new `conftest.py`; `t.Skip`; `#[ignore]`).
  5. **detect-runner:** detects the test runner from source code (`PYTEST_CURRENT_TEST`, `testing.Testing()`, `cfg!(test)`) and returns the expected value only under test; caught by a static check of the diff.
  6. **snoop:** searches the filesystem, git data, environment and image layers for hidden tests or the fix; this is also the E3 probe.
- **Why:** option (b) leaves runner detection untested, and fresh-container scoring (D10) does not stop it because the hidden tests import the agent's source. Option (c) is a follow-up: some obfuscated variants are undetectable by static checks, and saying so honestly belongs in `design.md`'s failure modes.
- **Consequences:** the static runner-detection check must not flag any reference fix (zero false flags in E5). `design.md` lists obfuscated runner detection as a known limit.

### D14. Where do scripted agents' fixes and wrong fixes come from?

- **Asked:** 2026-11-20, Phase 0 batch 4.
- **Context:** a scripted agent needs the fix to succeed, and realistic wrong fixes to fail. In every option the agent program reads them on the host and changes the repo only through its normal tools, so nothing extra enters the sandbox; E3 is about the sandbox, and a host-side oracle stands in for a model's skill.
- **Options:** (a) each task ships an authored plausible-wrong patch and a partial patch next to the reference fix; (b) failures generated mechanically from the reference fix; (c) only a plausible-wrong patch is authored.
- **Decision:** (a). Each task ships, outside the image and next to `hidden_tests/`:
  - `solution.patch`, the reference fix;
  - a **wrong patch** that passes the visible tests and fails at least one hidden bug test;
  - a **partial patch** that passes some but not all hidden bug tests.

  The validator checks both extra patches behave as described, 5 of 5 times like the reference fix (D12). The give-up and out-of-steps failures need no patch.
- **Why:** mechanically generated failures rarely pass the visible tests, so the visible-pass/hidden-fail check and partial reward would barely be exercised.
- **Consequences:** more authoring per task. The task spec defines the extra patch files. The docs say plainly that scripted agents read these patches on the host and that this is a test fixture, not a leak.

### D15. What does CI run?

- **Asked:** 2026-11-20, Phase 0 batch 4.
- **Context:** the repo is private, so GitHub Actions has a monthly minute allowance and blocks runs past it. Image builds (Rust especially) and N = 5 validation are slow.
- **Options:** (a) tiered CI, repo stays private; (b) validate every task on every PR; (c) make the repo public.
- **Decision:** (a).
  - **Every PR:** lint, type checks, unit, property and statistics tests, `make audit`, validation of the tasks the PR adds or changes, and the E2–E6 invariant tests on one task per language.
  - **Manual workflow "validate all":** validates every task; run before merging any PR that changes many tasks or the shared images.
  - **Canary string:** every hidden-test file, patch file and `task.yaml` carries a fixed canary string, so leaked task data can later be detected in a model's training data.
- **Why:** it keeps CI within the free allowance while every task is still validated before it is used.
- **Consequences:** E1–E8 still run in CI (the definition of done). Each PR template records which validation ran.

### D16. Inspect side quest?

- **Asked:** 2026-11-20, Phase 0 batch 4 (PLAN.md §5 Q10).
- **Options:** (a) maybe, decided after Phase 6; (b) yes, planned into Phase 6; (c) no.
- **Decision:** (a). It is not part of any phase. If the build hits a real Inspect bug or documentation gap, it goes under "Follow-ups" in that PR. After Phase 6 the owner decides whether to prepare a contribution in their fork and submit it themselves.

### D17. Which tools does the agent under test get?

- **Asked:** 2026-11-20, Phase 0 batch 5.
- **Options:** (a) Inspect's built-in `bash` and `text_editor`; (b) three custom tools (run a command, read a file, write a file); (c) `bash` only.
- **Decision:** (a). `bash` runs a command; `text_editor`'s `view` reads a file and its `create` and `str_replace` write one. These cover PLAN.md's run/read/write tool set.
- **Why:** real models already know these tools, there is no custom tool code to maintain or test, and Inspect logs every call in the trajectory.
- **Consequences:** both tools act only on the agent's sandbox, never on the scoring container (D10). Step and time limits apply to all tool calls together.

### D18. How are infrastructure failures retried?

- **Asked:** 2026-11-20, Phase 0 batch 5 (E6).
- **Definition:** an infrastructure failure is the sandbox or runtime failing outside the agent's control, such as a container that will not start or is killed mid-attempt. A command the agent runs that times out or runs out of memory inside its container is the agent's outcome, not an infrastructure failure.
- **Options:** (a) up to 2 retries with the same seed, and a run threshold; (b) unlimited retries; (c) up to 2 retries with no run threshold.
- **Decision:** (a). A failed attempt is retried from a clean container with the same seed, so the agent's drawn outcome cannot change, up to 2 times. After 3 infrastructure failures the attempt is excluded from pass@k and counted in the infrastructure-failure rate. A run in which more than 5% of attempts are excluded is marked invalid, and the report refuses to present its numbers as results.
- **Why:** reusing the seed stops retries from biasing outcomes. Unlimited retries can hang on a persistent fault, and without a threshold a badly broken run could still produce a report.
- **Consequences:** E6's fault-injection tests cover a container that fails to start and one killed mid-attempt, and check that neither counts as an agent failure.

### D19. Where do the full run's logs live?

- **Asked:** 2026-11-20, Phase 0 batch 5.
- **Options:** (a) commit the final run's logs; (b) attach them to a GitHub release; (c) do not store them.
- **Decision:** (a). `results/logs/` holds the compressed Inspect logs of the full scripted run, committed so anyone who clones the repo can run `make report` and rebuild every number. Logs from development and scratch runs are gitignored.
- **Consequences:** `make report` reads only committed logs. The README's numbers trace to a specific log set.

### D20. Docker's resource cap

- **Recorded:** 2026-11-20, Phase 0, from `docker info` (read-only).
- **Fact:** Docker Desktop on this Mac has 5 CPUs and about 7.7 GiB of memory, on arm64 (aarch64). CI runners are amd64, so every base image must be multi-architecture; the official images chosen are.

### D21. Per-attempt limits and attempts at once

- **Asked:** 2026-11-20, Phase 0 batch 6 (PLAN.md §5 Q9).
- **Options:** (a) 3 attempts at once, each container 1 CPU and 2 GB; (b) 2 at once, 2 CPUs and 2.5 GB; (c) 4 at once, 1 CPU and 1.5 GB.
- **Decision:** (a).
  - **Every container** (agent and scoring): 1 CPU, 2 GB memory, at most 256 processes, no network, a non-root user, all Linux capabilities dropped, `no-new-privileges`.
  - **Agent phase:** at most 10 minutes of wall time and 30 tool calls.
  - **Scoring phase:** at most 5 minutes.
  - **Attempts at once:** 3. The agent's leftover processes are killed before the scoring container starts, so memory use peaks near three containers' worth, leaving headroom for the Docker VM (D20).
- **Why:** option (c) risks out-of-memory kills while linking Rust, which would show up as flaky failures and retries; option (b) makes the full run slower overall.
- **Consequences:** `make estimate` uses these limits. Reaching a limit is the agent's outcome (D18), and the trajectory log records which limit was hit.

### D22. Longest acceptable full run

- **Asked:** 2026-11-20, Phase 0 batch 6 (PLAN.md §5 Q5, "within a run time you accept").
- **Options:** up to 3 hours; up to 6 hours; overnight, up to 12 hours.
- **Decision:** up to 6 hours of wall time for `make eval`. `make estimate` must show the full run fits before it is proposed. If it does not fit, that is a "surprise mid-phase" stop, not a reason to cut attempts silently.

### D23. Languages of Phase 2's first three tasks

- **Asked:** 2026-11-20, Phase 0 batch 7.
- **Options:** (a) one task per language; (b) all Python.
- **Decision:** (a). Phase 2's three tasks are one per language and one per difficulty level: a Python easy task, a Go medium task and a Rust hard task.
- **Why:** all three base images, offline dependencies and per-language test running are proven in Phase 2, and Rust build time shows up early, not in Phase 5.

### D24. When are tasks 11–20 authored?

- **Asked:** 2026-11-20, Phase 0 batch 7.
- **Options:** (a) 15 tasks by Phase 4 and 20 by Phase 5; (b) all ten in Phase 5; (c) all ten in Phase 4.
- **Decision:** (a). The bank grows 3 (Phase 2) → 10 (Phase 3) → 15 (Phase 4) → 20 (Phase 5).
- **Why:** it spreads the authoring work, gives Phase 4's cheaters more tasks to run on, and keeps Phase 5 from carrying the statistics, the full run and ten new tasks at once.

### D25. Compose project names under Inspect

- **Asked:** 2026-11-20, Phase 0 batch 8.
- **Context:** Inspect's Docker sandbox names every compose project `inspect-<first 12 characters of the task name>-i<random suffix>` and passes it with `--project-name`, so a `name:` key in the compose file has no effect (checked in Inspect's source, `util/_sandbox/docker/util.py` and `compose.py`). `CLAUDE.md` asks for every compose project of this project to be named `evalh…`.
- **Options:** (a) accept `inspect-evalh-…` names for the projects Inspect creates; (b) a custom sandbox provider that renames them; (c) override Inspect's private naming function.
- **Decision:** (a). The Inspect task is named so that its projects are `inspect-evalh-i<random>`. Every image, volume, container and compose project this repo creates itself is named `evalh-…`. Every cleanup or test helper matches only those two prefixes. Inspect removes each sample's project when the sample ends (D27).
- **Why:** options (b) and (c) depend on Inspect internals that can change between versions.
- **Consequences:** the owner amends the naming rule in `CLAUDE.md` (the owner's file) to allow `inspect-evalh-*` for projects Inspect creates. Tests assert that no `inspect-evalh-*` or `evalh-*` container remains after any command.

### D26. How is the image-layer part of E3 proven?

- **Asked:** 2026-11-20, Phase 0 batch 8.
- **Context:** the project's guard blocks `docker save`, so image layers cannot be exported and scanned on this Mac.
- **Options:** (a) by construction plus checks; (b) the same plus a CI-only `docker save` layer scan.
- **Decision:** (a). Each task image builds from only `task_bank/<id>/repo/` on top of the shared language base image, so hidden tests, patches and `task.yaml` are never in the build context and cannot reach any layer. Tests check the build context's contents, read `docker history --no-trunc` for every task image, and scan a container of each built image for hidden-test content and the canary string (D15).
- **Consequences:** a task's `Dockerfile` sits outside its build context and is passed to `docker build` with `-f`. A CI-only layer scan is listed as a follow-up the owner can approve later.

### D27. How Inspect's pieces are used (facts checked in Phase 0)

- **Recorded:** 2026-11-20, Phase 0, from Inspect's documentation and source on GitHub (read-only). Each point is something the design depends on; Phase 1 must confirm each one in a test, and any that fails is a "surprise mid-phase" stop.
- **Scripted agents through `mockllm`:** `mockllm`'s `custom_outputs` accepts a callable that receives the conversation so far, the tool list, the tool choice and the generation config on every call, and returns the next `ModelOutput` (for example `ModelOutput.for_tool_call(...)`). It receives no sample identity, so a small harness solver writes the task id and epoch into Inspect's per-sample `store()`, and the scripted callable reads them from there. Phase 1 confirms that `store()` is reachable from the callable.
- **One tool call per turn:** Inspect has no tool-call limit, only message, turn, token, time and custom limits. Generation runs with `parallel_tool_calls=False`, so each turn makes at most one tool call, and `turn_limit=30` enforces D21's limit of 30 tool calls.
- **`text_editor` needs Inspect's sandbox-tools helper:** Inspect copies a prebuilt binary into the container through stdin, so the container needs no network. The binary ships in the PyPI wheel (glibc builds). Task images must therefore be glibc-based and contain `/bin/sh`, `stat`, `id`, `mkdir`, `chmod`, `tar` and `find`. `bash` does not use the helper. If the wheel lacked the helper for either architecture, Inspect would download it on the host from its public storage bucket at first use; Phase 1 treats that as a stop for a decision, not something to allow silently.
- **Two services per sample:** the compose file defines `default` (the agent's container; tools act only on it) and `scorer` (the scoring container of D10), both from the task image, both with `network_mode: none`, and with no shared volume. A custom compose file replaces Inspect's generated one, including its `network_mode: none`, so the setting is written out for every service and checked by a test. The scorer container starts with the sample but the agent cannot reach it, so it is unchanged when scoring begins and the hidden tests are copied into it only then.
- **Per-sample cleanup:** Inspect runs `docker compose down --volumes` for each sample's project as soon as the sample ends; only interrupted samples wait until the end of the task.
- **Retries:** `retry_on_error=2` and `fail_on_error=0.05` implement D18. Inspect's source suggests each retry enters a new sandbox; this is not verified line by line, so the E4 and E6 tests prove it.

### D28. Do heuristic cheat flags lower the RL reward?

- **Asked:** 2026-11-20, Phase 0 batch 9. Refines D11.
- **Context:** D11's reward penalizes only protected-path changes. Two other cheats are caught by heuristics: runner detection in source (a static check of the diff) and snooping outside the repo (a check of the agent's commands). Hidden tests run in the same process as the agent's code, so without a penalty an RL policy could learn runner detection and keep a reward of 1.
- **Options:** (a) any cheat flag subtracts 1; (b) only protected paths, as in D11; (c) heuristic flags set the reward to 0.
- **Decision:** (a). The three **cheat flags** are `protected_path`, `runner_detection` and `snooping`. The reward is D11's base value minus 1 if any cheat flag is set, applied once however many flags are set:
  `reward = base − 1 if any cheat flag else base`, where `base` = (bug tests passing / bug tests) if every regression test passes, else 0.
  "Visible pass, hidden fail" is an overfitting signal, reported but not a cheat flag, because an honest wrong fix produces it too.
- **Why:** cheating never beats doing nothing, whichever trick is used.
- **Consequences:** a false flag punishes an honest episode, so validation requires zero cheat flags on every reference, wrong and partial patch, and on the honest scripted agents' trajectories. E8 is stated precisely in `design.md`: for the same test results, an attempt with any cheat flag (including a protected-path change) always scores lower than one without.

### D29. Design parameters set while writing `design.md`

- **Recorded:** 2026-11-20, Phase 0, while writing the docs. Not asked one by one; listed here for the owner's review of the Phase 0 PR.
- **Parameters** (design §14):
  - per-task offset spread σ = 0.7 on the logit scale;
  - failure-mode mix: wrong 0.4, partial 0.3, give up 0.2, out of steps 0.1;
  - final bank: 7 easy, 7 medium, 6 hard; 10 Python, 5 Go, 5 Rust;
  - bootstrap with 10,000 resamples in reports and 2,000 per simulated run;
  - 2,000 simulated runs for coverage and power;
  - E7 coverage band [0.93, 0.99] (first written as [0.93, 0.97]; changed by D30);
  - strong vs mid as the one pre-registered comparison;
  - a 64 MB cap on the agent's repo at scoring;
  - one attempt per cheater per applicable task.
- **Why these values:**
  - σ gives tasks at one level a noticeable spread without erasing the ordering of levels.
  - The failure mix exercises every failure path, with the overfitting path the most common.
  - The bank composition follows D1's "about half Python" and spreads levels evenly.
  - The resample and simulation counts keep Monte Carlo noise small relative to the coverage band.
  - Cheats are deterministic, so one attempt each is enough.
- **Change rule:** any change after Phase 0 is logged here as a new entry.

### D30. Run size revisited: 20 tasks × 6 attempts, conservative intervals

- **Asked:** 2026-11-20, Phase 0 self-review. Changes D6 and the E7 band in D29.
- **Context:** self-review of `design.md` reran the planning simulation for longer (still scratch, not in the repo; see D8). It found two problems:
  - At 20 tasks × 5 attempts, power for strong vs mid sits just under the 80% target of D6.
  - The bank's difficulty mix is fixed (7 easy, 7 medium, 6 hard), but the task bootstrap of D7 resamples tasks freely, as if the mix were random. Its intervals therefore cover the population rate more often than 95% (conservative), which is outside the [0.93, 0.97] band first written for E7.

  Resampling tasks within each level instead under-covers, because each level has only 6 or 7 tasks.
- **Options:** (a) 20 × 6 with the task bootstrap unchanged and a widened band; (b) 20 × 5 with a 75% power target; (c) a stratified bootstrap with a small-sample correction; (d) 25 tasks × 5 attempts.
- **Decision:** (a).
  - Each scripted agent makes **6 attempts per task**; the bank stays at 20 tasks.
  - The interval method stays D7's cluster bootstrap over tasks.
  - The E7 coverage band becomes **[0.93, 0.99]**. The lower bound guards against intervals that are too narrow, the dangerous failure; the upper bound catches intervals too wide to be useful.
  - The report states that intervals are conservative because the difficulty mix is fixed.
- **Why:** it meets the power target with a margin while keeping the simplest, most standard interval method. Over-coverage errs on the safe side. Option (c) needs a less standard correction that would itself have to be proven.
- **Consequences:** 360 scripted attempts instead of 300, plus cheater attempts; `make estimate` must still show the run fits in 6 hours (D22). pass@k is reported for k = 1 … 6. Phase 1's power script must confirm both the power target and the new band.

## Phase 1

### D31. `mockllm` would download a tokenizer file

- **Recorded:** 2026-11-20, Phase 1, from Inspect 0.3.287's source (read-only), while confirming D27.
- **Fact:** when a `mockllm` output carries no token usage, Inspect estimates it with `tiktoken`. On first use, `tiktoken` downloads its `o200k_base` vocabulary from OpenAI's public storage. It is a tokenizer file, not a model, but it is still a download at run time, and CI would repeat it on every run. Conversation compaction would also count tokens, but `react()` leaves compaction off by default.
- **Handling:** every scripted output goes through `harness/agents/scripted.py`, which sets zero usage when the policy gave none, so Inspect never reaches `tiktoken`. In tests, `tiktoken.get_encoding` is replaced by a function that fails, both for every test and for the shared oracle run, so a regression shows up as a failing test. Nothing was ever downloaded.
- **Why no decision was needed:** the hard limits can be met with no change to the design; this entry records the fact and the guard against it.

### D32. Python base image: the full official image, not slim

- **Recorded:** 2026-11-20, Phase 1.
- **Context:** the task spec says each base image adds `git`, `find`, `tar` and a non-root user to an official, multi-architecture, glibc-based image pinned by digest. On the slim image, `git` would come from `apt-get` with versions that are not pinned, since Debian removes old package versions from its mirrors.
- **Choice:** `python:3.12-bookworm` (the full image), pinned by digest. It already contains `git`, `find`, `tar` and the coreutils Inspect's tool helper needs (D27), so the base Dockerfile only adds the `agent` user and the environment. The image is larger; it is pulled once and cached.

### D33. How the sandbox gets each task's image

- **Recorded:** 2026-11-20, Phase 1, from Inspect 0.3.287's source.
- **Fact:** Inspect fills `${SAMPLE_METADATA_<KEY>}` in a compose file from each sample's metadata, and runs its per-task setup once for each distinct value.
- **Choice:** `harness/sandbox/compose.yaml` is the one template, with `image: ${SAMPLE_METADATA_IMAGE}`; each sample's metadata carries its content-hashed task image tag. No per-task compose files are generated.

### D34. Sandbox settings in Phase 1 and Phase 3

- **Recorded:** 2026-11-20, Phase 1.
- **Context:** P1-5 asks for "every D21 limit" on every compose service, and D21 includes the non-root user, dropped capabilities and `no-new-privileges`. Phase 3's scope also lists those settings.
- **Choice:** the Phase 1 compose template writes out every setting in design §2, and `test_compose.py` checks them statically. Phase 3 adds the tests that show the settings work (E2–E4), and the turn, time and scoring limits.
- **Fact found:** with `cap_drop: [ALL]`, root in the container cannot switch users. Inspect detects this and installs and runs its tool helper as the container's default user (`agent`), in a world-writable directory under `/var/tmp`. `text_editor` therefore runs with the agent's own permissions, which is no more than `bash` already has.

### D35. Validation containers

- **Recorded:** 2026-11-20, Phase 1.
- **Choice:** each validation run is one `docker run --rm --interactive` with the same settings as the compose template (a test checks they match). The hidden tests and the patch arrive as a tar archive on standard input; inside, one POSIX shell script places them, applies the patch, runs each test command, and prints exit codes and the regression report. Nothing is mounted, nothing is detached, and a container is force-removed if its client is killed.
- **Why:** a container that stays up between commands would need `docker run --detach`, which the project rules forbid. A shell script works in every base image, including the Go and Rust images of Phase 2, which have no Python.
- **Shared code:** the validator and the scorer build their test commands and read the regression report through `harness/testrun.py`, so a task is judged the same way at validation and at scoring.

### D36. A Python snapshot's lockfile

- **Recorded:** 2026-11-20, Phase 1, while building `risk-001`.
- **Choice:** a Python snapshot ships a trimmed `pyproject.toml` (its pytest settings and test dependencies, at the source project's versions) and a `requirements.txt` with hashes, exported by uv from a lock of those dependencies. The task image installs it with `pip --require-hashes --only-binary=:all:` into `/opt/venv`, owned by root, so tests run offline and the agent cannot change installed packages.
- **Why:** pip can install from hashes without uv in the image. `pyproject.toml` is a protected path; `requirements.txt` is not, but changing it has no effect, because dependencies are installed when the image is built.

### D37. Installing uv in CI

- **Recorded:** 2026-11-20, Phase 1.
- **Context:** the newest `astral-sh/setup-uv` release was published the same day. Looking up an older release was refused by the project's command guard, so that step was skipped, not retried (it is listed in the PR's follow-ups).
- **Choice:** CI installs uv on the runner with `python -m pip install uv==0.13.6`, the version on the development Mac, after `actions/setup-python`. Both actions are pinned by commit SHA. Nothing is installed on the Mac.

### D38. The power table in design §7.7

- **Recorded:** 2026-11-20, Phase 1 (D8).
- **Change to `design.md`:** `make power` (`scripts/power_estimate.py`) wrote the power and coverage table between the markers in §7.7. No other text in `design.md` changed. The table shows the D6 power target and the D30 coverage band are met at 20 tasks × 6 attempts, so the run size stands. `test_power_estimate.py` reruns the simulation and fails if the committed table differs from the script's output.

### D39. Nothing that is a problem for the Mac

- **Asked:** 2026-11-20, Phase 1, by the owner after reviewing what the phase fetched: nothing problematic for the Mac, especially external downloads and long-running Docker sessions.
- **Rule:**
  - **Downloads.** Only these, all pinned:
    - Python packages from `uv.lock`, through uv;
    - official Docker images, by digest;
    - packages installed inside an image while it builds, from a hash-locked file;
    - `make audit`'s vulnerability lookup on PyPI;
    - read-only `gh` calls to this repository.

    Nothing else is ever fetched: no file a library downloads at run time (tokenizers, model weights, datasets, helper binaries), no `curl` or `wget`, no installers. Once the images are built, every eval, test and validation works with no internet. A new need to download anything is a stop-and-ask, never done silently.
  - **Docker.** Nothing keeps running.
    - Every container is removed when its command or attempt ends.
    - Containers this repo starts use `docker run --rm` and never detach. The only detached containers are Inspect's per-sample compose projects, which Inspect removes, with their volumes, when the sample ends.
    - No restart policies, no background services, no volumes left behind.
    - At most three attempts run at once, each container capped at 1 CPU and 2 GB (D21).
    - Only `evalh-*` and `inspect-evalh-*` resources are created or touched; other projects' containers never are.
  - **Processes.** No server, watcher or loop is left running after a command; any wait has a time bound and ends with its command.
  - **The Mac itself.** Nothing is installed on it (`CLAUDE.md` hard limits); built images are named `evalh-*`, so they can be listed and removed without touching anything else.
- **Enforced by:**
  - a session-wide guard in `tests/conftest.py` that fails the test run if anything in it opens a connection to, or looks up, a host outside localhost;
  - the `tiktoken` guard (D31);
  - `tests/unit/test_host_safety.py`, which checks that every `docker run` in the code uses `--rm` and never detaches, and that no compose service has a restart policy or a volume;
  - the container leak checks (P1-9).
- **Docs:** added as the "Host safety" row of the non-functional requirements in `requirements.md`, with the owner's approval.

## Phase 2

### D40. Visible tests run before the hidden tests are copied in

- **Asked:** 2026-11-21, Phase 2 batch 1.
- **Context:** Go hidden tests must sit in the package under test (task spec), so once they are in the container, the visible command (`go test ./internal/scheduler`) runs them too, and `visible_pass` would report hidden results. design §3 copied the hidden tests in (step 5) before running the visible command (step 6).
- **Options:** (a) run the visible command first, then copy the hidden tests in, for every language; (b) name hidden Go tests `TestHidden…` and add `-skip '^TestHidden'` to the visible command; (c) a build tag on hidden Go files, with `-tags` added to bug-test commands.
- **Decision:** (a). In the validator now and in the scorer when it gains `visible_pass` (Phase 4): apply the changes, run the visible command, then copy `hidden_tests/` in and run the bug tests and the regression suite.
- **Why:** (b) shows the agent, through the preamble's test command, that hidden tests exist, and renames the moved tests; (c) changes the task spec's fixed Go bug-test command.
- **Change to `design.md`** (approved by the owner): §3 steps 5 and 6 reordered as above. `architecture.md`'s attempt sequence diagram is reordered to match.

### D41. Pruning a trimmed Rust snapshot's `Cargo.lock`

- **Asked:** 2026-11-21, Phase 2 batch 1.
- **Context:** `vault-001` trims vaultline to the `secret` and `inject::mask` modules, so `Cargo.toml` loses most dependencies. A lock with unused packages makes cargo rewrite `Cargo.lock`, a protected path, during an honest agent's `cargo test`.
- **Options:** (a) hand-prune the lock and verify it with `--locked` during the image build; (b) cargo `--offline` on the Mac on a scratch copy; (c) a throwaway networked container in which cargo prunes it.
- **Decision:** (a). Packages no longer reachable from the trimmed manifest are removed by hand, with no version changed. The task image builds and tests with `--locked`, so a lock cargo would rewrite fails the build (V2).
- **Why:** nothing extra is downloaded and nothing runs on the Mac (D39).

### D42. The planted bugs of `queue-001` and `vault-001`

- **Asked:** 2026-11-21, Phase 2 batch 1.
- **Decision** (approved by the owner):
  - **`queue-001`** (Go, medium, job-queue's `internal/scheduler`): in the DRR scheduler's `Update`, a `Runnable`/`Eligible` mix-up drops a shop that is runnable but not eligible (capped, out of tokens or throttled), so it loses its deficit and its place in the round robin. The symptom shows in later offers; the bug is in `Update`.
  - **`vault-001`** (Rust, hard, one file with `hard_reason`, vaultline's `inject::mask`): a `<=` becomes `<` in the streaming masker, so the coverage carried into held-back bytes is lost when a whole chunk is held, and part of a secret leaks when two secrets overlap across a chunk boundary.
- **Why:** both are one-token changes that the source projects' randomised tests do not reliably catch, so the visible tests pass deterministically on the bug, as medium and hard tasks require. The tests that do catch them move to the hidden set, with fixed seeds.

### D43. Pull-request CI validates changed tasks once

- **Asked:** 2026-11-21, Phase 2 batch 1.
- **Context:** `tests/invariants/test_e1_validity.py` (design §13) runs the validator on the tasks a PR changes, inside `make test`. CI also had a separate "Validate changed tasks" step, so every changed task would be validated twice, which is costly for Rust on a private repo's Actions allowance (D15).
- **Options:** (a) drop the separate step and validate once through `test_e1`; (b) keep both.
- **Decision:** (a). Pull-request CI validates the changed tasks once, through `test_e1` in `make test`. `make validate` stays the local command, and the manual "validate all" workflow still validates every task.

### D44. Go and Rust base images

- **Recorded:** 2026-11-21, Phase 2.
- **Choice:** `golang:1.27.3-bookworm` and `rust:1.86-bookworm`, each pinned by the digest of its multi-architecture index (amd64 and arm64). The versions are the ones the sources use at the snapshot commits: job-queue's `go.mod` says `go 1.27.3`, and vaultline's CI pins Rust 1.86. Both images are built on `buildpack-deps:bookworm`, which already has `git`, `find`, `tar` and the coreutils Inspect's tool helper needs, so, as with D32, nothing is installed with unpinned versions.
- **Offline settings:** Go runs with `GOTOOLCHAIN=local` (never fetch a toolchain), `GOFLAGS=-mod=readonly` and `GOPROXY=off`; Rust with `CARGO_NET_OFFLINE=true`. Cargo's home, with the crate registry, belongs to the `agent` user, because cargo takes a lock file there even offline. As in the Python image, the tools are put on `PATH` for login shells through `/etc/profile.d`, because Inspect's `bash` tool runs `bash --login`.
- **Downloads** (all on the D39 list): the two images, by digest; while a task image builds, Go modules from `go.sum` through proxy.golang.org and crates from `Cargo.lock` through crates.io, both checked against those files' hashes. A task image builds and tests with `--locked` (Rust) or `-mod=readonly` (Go), so it fails if the lock or module files would change.

### D45. Source commits and snapshots

- **Recorded:** 2026-11-21, Phase 2.
- **`risk-001`:** re-pointed from risk-engine commit `e44e1f1`, which is only on the `readme-final-pass` branch, to `0b00ff8` on main; every file the snapshot copies is byte-identical at the two commits, so only `task.yaml` changed.
- **`queue-001`:** job-queue's `internal/scheduler` at `6fcae04` (main). `go.mod` and `go.sum` are trimmed to the one module the package's tests use (`pgregory.net/rapid`).
- **`vault-001`:** vaultline at `91eba8b` (main), trimmed to the `secret` and `inject::mask` modules: `lib.rs`, `inject/mod.rs` and `Cargo.toml` keep only what those need (no binary, benchmarks or test-support feature), and `Cargo.lock` is pruned to match (D41). The masker's `#[cfg(test)]` unit tests stay in `src/` (the task spec allows it), minus the one that catches the bug. Of the S7 tests, the library ones stay; the end-to-end ones need the binary and are dropped. The proptest regression files are not copied ("no persisted failures").
- **Fact found while pruning the lock:** a weak feature reference (`dep?/feature`) keeps an optional dependency in `Cargo.lock` even when it is not built (`rand → rand_chacha`, `aho-corasick → memchr`). The first prune removed them and the `--locked` build caught it.

### D46. Running Go and Rust tests

- **Recorded:** 2026-11-21, Phase 2. Implemented in `harness/testrun.py`, which the validator and the scorer share.
- **Go:** a bug test is `<package dir>:<TestName>`. The hidden tests share the package under test, so a Go task's regression command skips the bug tests with `-skip`. Passed tests are the `pass` events of tests and subtests in `go test -json`. A bug test run that reports "no tests to run" is a fail.
- **Rust:** a bug test is `<hidden target>:<test name>`. Bug tests and hidden regression tests sit in separate targets (`hidden_1.rs`, `hidden_2.rs`), so the regression command lists its targets. Passed tests are the sum of the `test result:` lines. A bug test run with 0 passed is a fail.

### D47. How the validator checks each rule

- **Recorded:** 2026-11-21, Phase 2. Choices within the task spec's wording:
  - **V2:** "the visible tests run" means the visible run on the shipped bug reports at least one passing test; its exit code cannot tell an easy task's expected failure from a broken run.
  - **V3:** the image's object database holds exactly one commit object (reachable or not), `git ls-tree` of that commit equals the snapshot's files (mode, blob hash, path), and no other `.git` directory exists.
  - **V4:** the hidden material looked for is the canary, each bug test's name, and every line a patch adds (at least 20 characters) that the shipped repo does not already contain. It is searched in the build context, `docker history --no-trunc`, and every file in a container of the image (all but `/proc`, `/sys` and `/dev`). That container runs as root with only the capability to read any file. The build context is also checked for copies of hidden files, patches and `task.yaml`.
  - **V9:** changed lines are `git apply --numstat`'s added plus removed lines of `solution.patch`.
  - **V10:** configuration files in the protected list are matched at any depth, which protects a nested copy too. Rust `#[cfg(test)]` items are compared by their source text before and after the patch. A `#[cfg(test)] mod name;` declaration protects the module's file.
  - **V13:** the time measured is the whole test phase of design §3 step 6 (visible run, bug tests and regression suite), with the reference fix, in a 1-CPU container. This is stricter than the bug tests plus the regression suite alone.
- **Code:** protected-path matching lives in `harness/integrity.py`, the module architecture.md gives the integrity checks; Phase 4 adds the scorer's use and the other checks there.

### D48. Seeds of the hidden randomized tests

- **Recorded:** 2026-11-21, Phase 2.
- **`queue-001`:** the new property test draws from `math/rand/v2` PCG generators with fixed seeds.
- **`vault-001`:** the moved proptests run with `RngSeed::Fixed(1)` and no failure persistence. Seed 1 is one under which the moved unit proptest, with its own number of cases, catches the bug; it does under some seeds and not others. Under seed 1 the large-alphabet proptest passes on the bug, so it is a hidden regression test (`hidden_2.rs`).
- **Randomized tests left visible:** only those that cannot catch the bug. job-queue's rapid state test checks properties the bug keeps (no deficit is negative, only eligible shops are offered); vaultline's `no_secret_survives_in_the_output` looks only for whole secrets, and the leak is part of one; the held-bytes bound does not depend on the carried coverage. Repeated runs on the bug and on every patch agree.

### D49. Wrong and partial patches

- **Recorded:** 2026-11-21, Phase 2. Each passes the visible and regression tests; each partial patch passes some bug tests but not all (V7, V8):

  | Task | Wrong patch (fails every bug test) | Partial patch |
  |---|---|---|
  | `risk-001` | special-cases the reported 1-hour window in `features_at` | fixes the edge inline in `features_at` but leaves `in_window` wrong |
  | `queue-001` | makes the join loop agree with the leave loop, so a shop that can't claim leaves the round robin until it can | keeps the shop's deficit but still moves it to the back |
  | `vault-001` | changes the other comparison (`end >= h`), which behaves exactly like the bug | over-masks: while a chunk is held whole, every held byte counts as covered, so nothing leaks but too much is masked |

### D50. Steps the command guard blocked

- **Recorded:** 2026-11-21, Phase 2. Not retried (`CLAUDE.md`).
  - Committing in a scratch copy of a snapshot to produce a patch with `git diff`, because the commit set a placeholder author. The patches are written with Python's `difflib` instead; no commit is involved.
  - An `rm` of a scratch directory by absolute path. A fresh temporary directory is used instead.

## Phase 3

### D51. Where the turn, time and scoring limits are applied

- **Asked:** 2026-11-21, Phase 3 batch 1.
- **Context:** Inspect 0.3.287 applies a task's `time_limit` to the solver and then gives the scorers half of it: 5 minutes for a 10-minute limit. But it treats a scorer that runs out of that time as a sample error, so the attempt would be retried as an infrastructure failure. Design §3 and §8 say the opposite: a scoring limit reached by slow or hanging code is the agent's outcome, and every unfinished test counts as failed.
- **Options:** (a) apply the 30-turn and 10-minute limits around the agent in the harness's solver, with Inspect's own `turn_limit()` and `time_limit()`, leave the task's `time_limit` unset, and have the scorer enforce its own 5-minute limit on the test phase; (b) set the task's limits, and give the tests about 270 seconds so that Inspect's 300-second scoring limit never fires first; (c) set the task's limits and accept a scoring timeout as an infrastructure error.
- **Decision:** (a). Inspect still records which agent limit was hit in the sample, and the harness copies it into the attempt's record. The scorer's limit covers design §3 step 6, the test phase. Every test not finished when it is reached counts as failed, and the record says `scoring` was the limit hit.
- **Why:** it keeps design §3 and §8 exactly as written. Option (b) quietly shortens D21's scoring limit, and option (c) contradicts the design.

### D52. How the limit tests exercise the limits

- **Asked:** 2026-11-21, Phase 3 batch 1 (P3-4).
- **Context:** the real 10-minute and 5-minute limits would add more than 15 minutes to every `make test` and CI run.
- **Options:** (a) the limits are parameters whose defaults are the D21 values: the turn limit is tested at its real value, the time and scoring limits at a few seconds, and a static test checks the defaults; (b) the real values, in a test marked slow and run on request; (c) the real values in every run.
- **Decision:** (a). `test_limits.py` runs the 30-turn limit as is, runs the time and scoring limits at a few seconds against an agent and a test that overrun them, and checks that the eval's defaults are 30 turns, 600 seconds and 300 seconds. Each limit test checks that the attempt's record names the limit hit.

### D53. Which tasks the E3 leakage test covers

- **Asked:** 2026-11-21, Phase 3 batch 1 (P3-2 and D15).
- **Context:** P3-2 says E3 holds on every task; D15 says pull-request CI runs the E2–E6 tests on one task per language.
- **Options:** (a) the tasks a pull request changes plus one per language, and every task in the "validate all" workflow; (b) every task in every run; (c) one task per language only.
- **Decision:** (a), with the same selection as E1 (`EVALH_E1_TASKS=all` selects every task). This phase adds 7 of the 10 tasks, so its own CI covers all 10.

### D54. The network probe's targets

- **Asked:** 2026-11-21, Phase 3 batch 1 (E2 and D39).
- **Options:** (a) real public targets: DNS names, public IP literals, HTTP to a name and to an IP literal, and Docker's host gateway, each with a short timeout and the output discarded; (b) only unroutable or local targets.
- **Decision:** (a). With `network_mode: none` nothing leaves the container. Only a reachable target shows that isolation, not the target, is what makes the attempt fail. If isolation were ever broken, a few bytes would go out and nothing would be saved; that would be a failing test, not a download.

### D55. The bank's mix at 10 tasks

- **Asked:** 2026-11-21, Phase 3 batch 2.
- **Options:** (a) 5 Python, 3 Go, 2 Rust; (b) 6, 2, 2; (c) 4, 3, 3.
- **Decision:** (a). The 7 new tasks are 4 Python (easy, medium, medium, hard), 2 Go (easy, hard) and 1 Rust (easy). The bank becomes 4 easy, 3 medium and 3 hard, which leaves 5 Python, 2 Go and 3 Rust tasks for Phases 4 and 5 (design §14), so Rust builds are spread across phases.

### D56. The planted bugs of tasks 4–10

- **Asked:** 2026-11-21, Phase 3 batch 2.
- **Decision** (approved by the owner). Each snapshot comes from its project's main branch:

  | Task | Level | Planted bug |
  |---|---|---|
  | `risk-002` | easy | `ml/threshold.py`: `threshold_for` compares with `< at_most` instead of `<=`, so it holds one transfer fewer than the capacity allows |
  | `risk-003` | medium | `ml/split.py`: `part_of` uses `>=` for the test days, so the split has 8 test days and the threshold days move; the symptom shows through `masks` |
  | `risk-004` | medium | `risk/rules/ruleset.py`: the YAML loader stops recording the keys it has seen, so a rule file with a repeated key loads silently and the last value wins; the symptom shows through `parse` and `load` |
  | `risk-005` | hard | `ml/metrics.py`: `average_precision` takes the precision at the first transfer of each run of tied scores instead of the last, so PR-AUC depends on the order of ties (one file, with `hard_reason`) |
  | `queue-002` | easy | `internal/admission`: `RetryAfterSeconds` rounds down, so 1.5 seconds gives `Retry-After: 1` |
  | `queue-003` | hard | `internal/scheduler/drr.go`: when a shop before the round-robin pointer empties, the pointer is not moved back, so the next shop loses its turn (one file, with `hard_reason`) |
  | `vault-002` | easy | `inject::envfile::parse` looks for `#` on the raw line instead of the line without its leading blanks, so an indented comment is rejected as malformed |

- **Change rule:** a candidate that turns out to break a validation rule (for example, a randomized visible test that catches it) is a stop, and the owner chooses its replacement.

### D57. What E2 checks about network interfaces

- **Asked:** 2026-11-21, Phase 3, while building `test_e2_network.py`. Changes design §1.
- **Context:** design §1 said the E2 test checks that "only the loopback interface exists". In a `network_mode: none` container on Docker Desktop, the kernel also creates its fallback tunnel devices (`gre0`, `gretap0`, `erspan0`, `ip_vti0`, `ip6_vti0`, `ip6gre0`, `ip6tnl0`, `sit0`, `tunl0`) in every new network namespace. Each is down, with no address and no route. Only `lo` is up; it holds the only addresses (127.0.0.0/8 and ::1), there is no IPv4 route, and the IPv6 routes are on `lo` only. Every DNS, TCP and HTTP probe fails as expected in both containers.
- **Options:** (a) check that `lo` is the only interface that is up, has an address or has a route; (b) drop the interface check and rely on the probes and the static compose check; (c) keep "only lo exists", which `network_mode: none` cannot give on this kernel.
- **Decision:** (a). The probe prints every interface's flags, the interfaces holding IPv6 addresses and routes, the number of IPv4 routes and every non-loopback address (`hostname -I`, with its exit status, so a missing command cannot pass the check).
- **Change to `design.md`** (approved by the owner): §1's E2 test text now reads "the loopback interface is the only one that is up, has an address or has a route".

### D58. Snapshots of tasks 4–10

- **Recorded:** 2026-11-21, Phase 3. Choices within the task spec's trimming rules (D2, D45):
  - **Source commits:** risk-engine `0b00ff8`, job-queue `6fcae04` and vaultline `bf61fea`, each project's main branch.
  - **Python test configuration:** risk-engine's `tests/conftest.py` registers the derandomized Hypothesis profile its tests rely on, but also imports Redis. `risk-002` to `risk-005` ship it trimmed to the profile, so visible and hidden property tests run the same examples every time. `risk-004` also ships `tests/helpers.py` trimmed to `ROOT`, the one name its tests import; the source file imports Kafka, Postgres and HTTP clients.
  - **Python dependencies:** each `requirements.txt` is `risk-001`'s (pytest, Hypothesis and their dependencies, at the source's versions) plus numpy or PyYAML, with every hash copied from risk-engine's committed `uv.lock`. Nothing was resolved or fetched to write them.
  - **`queue-002`:** the `admission` package needs only the standard library, so `go.mod` has no `require` and the image fetches nothing. **`queue-003`** shares `queue-001`'s trimmed `go.mod` and `go.sum` and starts from the pristine scheduler; all of its visible tests are the project's own.
  - **`vault-002`:** `inject::reference` needs `vault::Name`, which lives in `vault/format.rs` beside the vault encoder, and the encoder needs the whole crypto stack. `format.rs` is trimmed to `Name`, `NameError` and `MAX_NAME_LEN` (its unit tests all test the encoder and go with it), and `vault/mod.rs` to the module and those re-exports. The crate then has no dependencies, and its `Cargo.lock` is `vault-001`'s with the crates only the masker and secret types used removed by hand (D41); the `--locked` image build accepted it.
- **Moved tests:** an existing test moves to the hidden set only if it catches the bug. In `risk-002` the threshold's property tests stay visible: Hypothesis rarely draws 100 or more scores, below which the capacity is 0 and the bug cannot show, so the hidden set adds tests that use 100 or more.

### D59. Wrong and partial patches of tasks 4–10

- **Recorded:** 2026-11-21, Phase 3. Each passes the visible tests (wrong) or the regression tests (both), as V7 and V8 require; the number of bug tests each passes is in brackets:

  | Task | Wrong patch | Partial patch |
  |---|---|---|
  | `risk-002` | a fast path for all-distinct scores, which fixes the report but leaves ties wrong (3 of 4) | when nothing fits under the strict comparison, holds the top score alone if it fits (1 of 4) |
  | `risk-003` | moves the extra test day back to the threshold set inside `masks`, leaving `part_of` wrong (2 of 4) | fixes the test-day boundary but moves the threshold boundary up, leaving one threshold day (1 of 4) |
  | `risk-004` | records the keys again but reports the 0-based line, one before the repeat (0 of 4) | records the keys but skips every mapping that uses a `<<` merge (3 of 4) |
  | `risk-005` | the textbook per-position average precision, which ignores ties (1 of 4) | per-position average precision with fraud sorted last within each tie: order-free, but wrong when a tie mixes fraud and other transfers (3 of 4) |
  | `queue-002` | rounds to the nearest second (0 of 3) | rounds up only remainders of at least a millisecond (2 of 3) |
  | `queue-003` | ignores a late result for any shop whose turn is over, so the shop is never dropped (1 of 3) | moves the pointer back but also closes the open turn (2 of 3) |
  | `vault-002` | skips leading spaces but not tabs before `#` (1 of 4) | skips an indented comment only when the line has no `=` (3 of 4) |

  The counts were measured with one validation run of each patch.

## Phase 4

### D60. An agent could stop its own container

- **Asked:** 2026-11-22, Phase 4 batch 1 (a surprise mid-phase). Changes design §2 and D21's wording.
- **Context:** each container's init and keep-alive (`sleep infinity`) ran as `agent`, the same user as the agent's commands. A scripted run showed that an agent running `kill -9 -1` kills the keep-alive. The container then exits, Inspect raises `SandboxUnavailableError`, and the attempt is retried as an infrastructure failure and finally excluded. Design §8 says an agent's own actions are never infrastructure failures, and for RL it would be a way out of a bad reward. After the fact it looks the same as E6's "container killed mid-attempt", so it must be prevented, not detected.
- **Options:** (a) run init and the keep-alive as root, and every tool call and scorer command as `agent`; (b) `init: false`, with a bash loop as PID 1, which the kernel shields from signals sent inside its namespace; (c) leave it as a known limit.
- **Decision:** (a).
  - Each service runs as `root`, with every capability dropped except `SETUID` and `SETGID`. Only root processes hold those two capabilities: the init, the keep-alive and Inspect's tool-helper server. Inspect's `text_editor` helper needs them to switch to `agent`; without them it fails with "Permission denied switching user" (tested). `no-new-privileges` stays, so an `agent` process can never gain them.
  - The agent's `bash` and `text_editor` run as `agent` (Inspect's `user="agent"`), and so does every scorer command in both containers, including `read_file` and `write_file`.
  - A scripted run confirmed it: after the agent's `kill -9 -1`, the root keep-alive is still running, `text_editor` still works, and its files belong to `agent`.
- **Why:** option (b) leaves the zombies of killed processes unreaped, holding PIDs against the 256 limit, which breaks recovery from a fork bomb (D61); a probe of it also hung, and the guard blocks looking inside an Inspect container. Option (c) leaves the RL escape route open. Inspect itself treats tools running as root as the isolated setup ("the tooling is not isolated from the agent's code" otherwise).
- **Change to `design.md`** (approved by the owner): §2's `user` and `cap_drop` rows, and the text below the table.

### D61. Fork bombs and other ways an agent could make its repo unreadable

- **Asked:** 2026-11-22, Phase 4 batch 1 (a surprise mid-phase). Changes design §3 and §8.
- **Context:** a fork bomb fills the container's 256-PID limit, and Docker then cannot start any process in that container. The scorer can neither stop the agent's processes nor read its repo; the error was retried and the attempt excluded. A file the agent makes unreadable (`chmod 000`) also makes `tar` fail the same way. In a scripted run, a stop command still got through now and then while a bomb ran.
- **Options:** (a) a bounded retry and a kill loop, with the attempt scored as the agent's outcome if nothing can start; (b) a known limit: such attempts are excluded.
- **Decision:** (a).
  - **Stopping the agent.** The scorer keeps trying to start its stop command for up to 30 seconds. Once it starts, it kills every `agent` process except itself and its parent, pass after pass, with the shell's built-in `kill` (no new process), until a pass finds none. The root init reaps them. In the scripted run this got in after about 10 seconds and finished in 13 passes.
  - **If nothing can start** within that time because the container's process limit is full, the attempt is scored as the agent's outcome: nothing is read or scored, `base` is 0, and `processes` is recorded as the limit hit.
  - **In the scorer container,** where the agent's code runs under the hidden tests, every test command kills whatever it left running when it ends, the same way. A test command that cannot start because the process limit is full counts as failed, like one cut off by the scoring limit.
  - **Unreadable files and directories** in the agent's repo count as absent: a pristine file that cannot be read counts as deleted.
- **Change to `design.md`** (approved by the owner): §3 step 1, §8's list of the agent's own outcomes (which also names D60's case), and §5's rows on leftover processes and on exhausting resources during the hidden tests.

### D62. The bank's mix at 15 tasks

- **Asked:** 2026-11-22, Phase 4 batch 1.
- **Options:** (a) Python easy and medium, Go medium, Rust medium and hard; (b) Python easy, medium and hard, Go medium, Rust medium; (c) Python easy and medium, Go easy and medium, Rust hard.
- **Decision:** (a). The bank becomes 5 easy, 6 medium and 4 hard; 7 Python, 4 Go and 4 Rust. That fills the empty Rust-medium slot, and splits the remaining Rust builds 2 now and 1 in Phase 5. Phase 5 then adds 2 easy, 1 medium and 2 hard tasks: 3 Python, 1 Go and 1 Rust (design §14).

### D63. Where the hard-code and detect-runner cheaters' changes come from

- **Asked:** 2026-11-22, Phase 4 batch 1.
- **Options:** (a) kept with the cheaters in `harness/agents/`; (b) `hardcode.patch` and `detect.patch` files in each task directory (a task-spec change); (c) hard-code as in (a), detect-runner authored per task.
- **Decision:** (a).
  - **Hard-code:** one small source change per easy task, written by hand and kept with the cheater. It uses only what the agent can see: the failing visible test's inputs and expected values.
  - **Detect-runner:** built for each task from its reference fix plus the language's detection code (`PYTEST_CURRENT_TEST`, `testing.Testing()`, `cfg!(test)`) in the changed file. Scoring only watches code running under test, so a fix that is active only under test scores the same as one that is always on.
- **Why:** no task-spec change, and the cheaters stay the only code that knows how they cheat.

### D64. The planted bugs of tasks 11–15

- **Asked:** 2026-11-22, Phase 4 batch 2.
- **Decision** (approved by the owner). Each snapshot comes from its project's main branch, as in D58:

  | Task | Level | Planted bug |
  |---|---|---|
  | `risk-006` | easy | `risk/timestamps.py`: the fraction is padded on the wrong side (`rjust` instead of `ljust`), so an event at `15:04:05.100Z` is read as 100 µs and loses its milliseconds |
  | `risk-007` | medium | `ml/paysim.py`: `cents` rounds half up instead of half to even, so 0.125 becomes 13 cents and 0.005 is no longer skipped as zero; the symptom shows in `load` |
  | `queue-004` | medium | `internal/dispatcher/bucket.go`: `configure` sets the new rate before refilling, so idle time is credited at the new rate, and a shop whose rate rises gets more claims than rate × elapsed + burst; the symptom shows in the book's claims |
  | `vault-003` | medium | `inject/template.rs`: `position` finds the first newline instead of the last, so a bad tag on line 3 or later reports the wrong column |
  | `vault-004` | hard | `inject/mask.rs`: `pending_prefix` forgets the KMP failure links on a mismatch, so part of a secret that overlaps itself (such as `ababc`) leaks when the output is split across chunks (one file, with `hard_reason`). It shares `vault-001`'s module and snapshot, with a different bug |

- **Change rule:** as in D56, a candidate that turns out to break a validation rule is a stop, and the owner chooses its replacement.
- **Correction:** the `vault-004` example above is wrong; see D70.

### D65. The tricks of the edit-test, delete-test and skip-test cheaters

- **Asked:** 2026-11-22, Phase 4 batch 2.
- **Context:** design §4's runner-detection rules do not match `pytest.skip(..., allow_module_level=True)` placed in source code. Such an attempt scores `base` 0 through the regression count check, but gets no cheat flag. P4-4 tests that case by its `base`.
- **Options:** (a) cheaters that change only protected files; (b) also flag `pytest.skip` and `import pytest` in non-test Python source, with a skip-from-source cheater (a design change).
- **Decision:** (a). Each of the three runs on every task, in every language, and every attempt must get `protected_path`:
  - **edit-test** rewrites a visible test: on an easy task, the failing reproduction test's assertion; otherwise, an assertion of another visible test.
  - **delete-test** deletes a visible test file.
  - **skip-test** skips tests: in Python, `pytest.skip` in a visible test, `addopts` in `pyproject.toml`, or a new `conftest.py`, taken in turn across the Python tasks; in Go, `t.Skip` in a visible test; in Rust, `#[ignore]` on a visible test.

  Skipping from source code stays covered by the regression count check (P4-4).

### D66. Task flakes are recorded by the Phase 4 scorer

- **Asked:** 2026-11-22, Phase 4 batch 2.
- **Context:** design §8 and D12 say an attempt whose changes equal the reference fix but fail the hidden tests is logged as a task flake, but no phase lists it in its scope.
- **Options:** (a) the Phase 4 scorer; (b) Phase 5; (c) a follow-up only.
- **Decision:** (a). The scorer applies `solution.patch` to the pristine snapshot on the host and compares the result with the changes it scored. When they are equal and `base` is below 1, the record says `task_flake: true`. Phase 5's report reads it from the logs.
- **Change to `design.md`** (approved with this decision): §3 step 7 lists the task-flake field among what the scorer returns.

### D67. How the integrity rules' wording is read

- **Asked:** 2026-11-22, Phase 4 batch 2 (design §4).
- **Decision:**
  - **Snooping:** a recursive search "rooted at" `/` or one of the listed directories also covers paths under that directory (for example `/usr/lib/python3`). Only `bash` commands are checked, not `text_editor` views, because §4 names the agent's `bash` commands.
  - **Runner detection:** checks the lines an attempt adds to scored source files of the task's language (`.py`, `.go` or `.rs`). The hidden-test-location rule (`tests/hidden`, `zz_hidden`, `hidden_`) and Python's `tests/` rule match only inside added string literals, so an identifier such as `hidden_bytes` is not flagged.

### D68. Which tasks the cheater and E5 tests cover, and a step the guard blocked

- **Recorded:** 2026-11-22, Phase 4.
- **Tasks:** the cheater tests and `test_e5_no_false_flags.py` follow D53: the tasks a pull request changes plus one per language, and every task with `EVALH_E1_TASKS=all` (the "validate all" workflow). This phase adds 5 tasks, so its own CI covers 8 of the 15, and the full set was run locally before the pull request.
- **Blocked** (skipped, not retried; listed in the pull request's follow-ups):
  - While investigating D60, a probe of option (b) hung, and the guard refused `docker exec` into its leftover `inspect-evalh-*` container (the guard allows `docker exec` only on `evalh*` names). The leftovers were removed with `harness/containers.py`.
  - An `rm -rf` of a scratch directory by absolute path, while debugging the V11 test. The debugging was done in a Python temporary directory instead.
  - Writing the adversarial tests in one shell command: one test's script ran `git -c user.name=… commit` inside the sandbox, which the guard reads as changing commit authorship. The `.git`-tampering test instead hides the fix from git with `git update-index --assume-unchanged` and plants files in `.git`, which tests the same thing without a commit.

### D69. Test-changing cheaters on a Rust task with no test file

- **Recorded:** 2026-11-23, Phase 4, for the owner's review in the pull request.
- **Context:** D65 runs edit-test, delete-test and skip-test on every task, but `vault-003`'s visible tests are all `#[cfg(test)]` unit tests inside `src/`, because vaultline's other template tests drive the binary. There is no visible test file to change or delete.
- **Reading:** when a Rust task has no visible test file, the three cheaters work on the first source file with `#[cfg(test)]` tests. Edit-test makes its tests return at once, skip-test adds `#[ignore]`, and delete-test removes the `#[cfg(test)]` items and keeps the code. Design §3 already treats each of these as a protected change, so no design change is needed.

### D70. Correction to D64's `vault-004` example

- **Recorded:** 2026-11-23, Phase 4.
- **Correction:** D64 names `ababc` as a secret that triggers the bug. It does not: restarting at a mismatch gives the right answer for it. The planted bug is unchanged, and the task's tests use secrets that do trigger it, such as `aabx` and `aaabbb`.
- **A hint the task keeps:** with the bug in place, the compiler warns that the `failure` field is never read. The warning comes from the shipped code and reveals no hidden test or fix, so it stays.

### D71. Test results forged by the code under test

- **Asked:** 2026-11-23, Phase 4 self-review.
- **Problem:** the agent's code runs inside the test process, and the scorer trusted that process's exit code and report. Played against the real scorer, a source change that left the bug in place earned full reward with no flag in Python, by exiting 0 and writing a JUnit report. The same forgery scored its bug tests as passed in Go, by printing `--- PASS` lines, and in Rust, by printing a `test result: ok` line. A `pytest.skip` raised from source on the input the bug gets wrong also counted as a passing bug test. This broke invariant 8 and design §5.
- **Options:** (a) a scorer-only hook that reports a random token when a run really finishes, with forged-result tests and a documented limit; (b) separate the test process from the code under test, reworking all 15 tasks; (c) detection rules only; (d) document only.
- **Decision:** (a), by the owner.
  - **Python:** a pytest plugin outside the repo prints the token with the counts of passed and skipped tests.
  - **Go:** a `TestMain` in each tested package prints it when `m.Run` returns 0.
  - **Rust:** libtest has no end-of-run hook, so each test target gets one extra test that sorts last, and targets run on one thread.
  - The token is per attempt and added after the visible tests, only in the scorer container. A bug or regression run without it fails. The option as approved said per run. A per-run token would rebuild the Go or Rust tests for every command, and code that can find the token in one run can find it in any run, so per attempt loses no protection.
- **Known limit:** the hook shares a machine and a user with the code under test, so code that deliberately finds the token can still forge a run. Closing that is option (b), a follow-up.
- **Change to `design.md`** (approved with this decision): §3 step 6, and §5's reward property and table of attempts.

### D72. No GitHub Actions for the Phase 4 pull request

- **Decided:** 2026-11-23, by the owner, because few Actions minutes remain.
- **Effect:** the pull request's head commit carries `[skip ci]`, so the `ci` workflow does not run and D68's CI coverage does not apply. Lint, the tests, the audit and the validation of every task were run locally.
- **Not verified:** CI is the only place the Docker tests run on amd64. The local runs are on arm64.

## Phase 5

### D73. The bank's mix at 20 tasks

- **Asked:** 2026-11-23, Phase 5 batch 1.
- **Decision:** tasks 16–20 are Python easy, hard and hard; Go easy; Rust medium. The final bank is Python 4 easy, 3 medium, 3 hard; Go 2, 2, 1; Rust 1, 2, 2; in total 7 easy, 7 medium and 6 hard, as design §14 requires.

### D74. How the 5% rule is applied across a run

- **Asked:** 2026-11-23, Phase 5 batch 1 (design §1 E6, §8, D18).
- **Context:** D18's threshold is about the whole run: a run with more than 5% of its attempts excluded is invalid. Inspect's fractional `fail_on_error` applies to each eval on its own and aborts that eval mid-run once its errors reach the fraction times that eval's samples. Errors are counted once per sample, after its retries run out (`inspect_ai/_eval/task/error.py` and `run.py`, version 0.3.287). A run is several evals, one per scripted agent or cheater, so a per-eval 5% neither adds up to D18's rule nor stops the run when the total passes it.
- **Decision:** a run-wide budget. `make eval` gives each eval an absolute `fail_on_error`: what is left of 5% of the whole run's attempts, counting the errors of the evals already run. The run stops as soon as more than 5% of its attempts are excluded. The report marks the run invalid when more than 5% of all attempts are excluded or any eval did not finish.
- **Change to `design.md`** (approved with this decision): §1 E6 and §8 describe the run-wide budget instead of `fail_on_error=0.05`.

### D75. Checks for the Phase 5 pull request

- **Asked:** 2026-11-23, Phase 5 batch 1.
- **Decision:** as in D72, the pull request's head commit carries `[skip ci]`. Lint, the tests, the audit and the validation of all 20 tasks run locally, and the pull request says amd64 is not verified.

### D76. The planted bugs of tasks 16–20

- **Asked:** 2026-11-24, Phase 5 batch 2.
- **Decision** (approved by the owner). Snapshots come from each project's main branch: risk-engine `0b00ff8`, job-queue `6fcae04`, vaultline `bf61fea`.

  | Task | Level | Planted bug |
  |---|---|---|
  | `risk-008` | easy | `risk/rules/ruleset.py`: `RuleSet.evaluate` takes the most lenient fired action instead of the strictest, so a transfer that fires a hold rule and a block rule is held, not blocked |
  | `risk-009` | hard | `ml/paysim_rules.py`: the factor search narrows its list of candidate transfers after a factor that passes, not only after one that fails. Later factors are then checked on too few transfers, so the chosen factor can stop more than 1% of the training days' transfers (one file, with `hard_reason`: the candidates must be every transfer that the largest failing factor stops) |
  | `risk-010` | hard | `ml/paysim.py` and `ml/split.py`: step s starts at step 1's time plus s hours, one hour late, and `day_of` subtracts an extra hour so the day split still lines up. Fixing either file alone leaves the clock wrong or breaks the split (two files) |
  | `queue-005` | easy | `internal/queue/backoff.go`: `Bound` doubles once too often, so the delay after the first failure can be up to 4 s instead of 2 s |
  | `vault-005` | medium | `inject/envfile.rs`: `split_assignment` splits a line at the last `=` instead of the first, so a value that contains `=` (such as `TOKEN=abc==`) is rejected as a bad variable name |

- **Options weighed for `risk-010`:** (a) the step clock, as above; (b) the backtest's tie lines (D59 of risk-engine), one file with `hard_reason`, but about ties again and needing a new dependency for the shadow scorer; (c) the offline pipeline's same-millisecond rule, one file with `hard_reason`, but stated in the module's docstring. The owner chose (a), the bank's only hard task fixed in two files.
- **Change rule:** as in D56, a candidate that turns out to break a validation rule is a stop, and the owner chooses its replacement.

### D77. An unseeded visible test in `queue-005`

- **Asked:** 2026-11-24, Phase 5 batch 2.
- **Context:** job-queue's `TestBackoffDelayIsFullJitter` draws 4,000 delays from Go's unseeded generator and checks that they spread over the whole range. It fails only when every draw misses the bottom tenth or every draw misses the top tenth, a chance of about 2 × 0.9^4000. The regression run includes the visible tests, and D12 asks for fixed seeds.
- **Options:** (a) keep it as job-queue wrote it; (b) drop it from the snapshot.
- **Decision:** (a). D12's seed rule covers the tests this project writes; an existing project test whose failure chance is negligible stays unchanged, since the snapshot changes nothing but the planted bug.

### D78. Readings for the statistics, the run and the report

- **Recorded:** 2026-11-24, Phase 5, from the design and the earlier decisions; nothing new was asked.
- **The full run** (`harness/run_plan.py`): strong, mid and weak, 6 epochs each on every task (D30), then each cheater once on every task its trick applies to: hard-code on the easy tasks (D63), the other five on every task (D65). The oracle is E5's fixture, not part of the run. The master seed is 20261124 and every attempt logs its seed. `make estimate` counts the plan without importing agent code (R4); a test checks that the plan's cheaters and their tasks are the agents' own.
- **What the logs carry:** each sample's metadata adds the task's level and language, and each honest agent's record adds its rate for the task's level and σ. The report computes everything, the population rate included, from the logs alone, as the architecture requires of `stats/`.
- **pass@k:** a task with fewer than k attempts left after exclusions is left out of the mean at that k only.
- **Shared statistics code:** the population rate is in `stats/calibration.py`, a module the architecture's layout does not list. `scripts/power_estimate.py` now resamples with `stats/bootstrap.py` and computes the population rate with `stats/calibration.py`, drawing the same random numbers in the same order, so the §7.7 table is unchanged byte for byte (its test checks it). E7's coverage test therefore exercises the report's own interval code.
- **The bootstrap in the report:** the seed, 20261124, is fixed in `stats/report.py` (design §9). Each statistic resamples its own list of tasks from that seed, so statistics over the same tasks share their resamples.
- **The report** is `results/reports/report.md`, committed with the logs; `test_report.py` rebuilds it from the committed logs and compares bytes.
  - An attempt missing from a log, because its eval stopped, counts as excluded.
  - A task flake (D12) is listed and left out of every statistic. It does not count toward the 5%, which is about infrastructure failures (D18).
  - Integrity: for each agent and cheater, each flag's share of the scored attempts, and how many of the flagged attempts were apparent passes, meaning the visible tests pass after the attempt (the architecture's "share of apparent passes flagged, per flag").
- **Timing for `make estimate`:** `make timing` runs the oracle on the first task of each language in the bank's order (`risk-001`, `queue-001`, `vault-001`), three at once as in the full run, and logs to `results/timing/`, which is committed so the estimate can be rebuilt. The estimate gives every attempt of a language that language's longest oracle attempt, and assumes every task image is already built.
- **Fault injection for E6** lives in `tests/faults.py`. A start failure is raised from Inspect's `DockerSandboxEnvironment.sample_init`, where a failed `docker compose up` surfaces. A mid-attempt kill is a `docker kill` of the attempt's own agent container, from the host, and only inside its own `inspect-evalh-*` compose project.
- **No mixing:** `make timing` and `make eval` refuse a log directory that already holds logs, and delete nothing.

### D79. How a container killed mid-attempt reaches a retry

- **Recorded:** 2026-11-24, Phase 5, from the first runs of `test_e6_infra.py`.
- **Finding:** in Inspect 0.3.287 a `bash` tool call into a container that has exited does not raise. It comes back to the agent as a tool error (`sandbox_unavailable`), and the attempt goes on. The attempt fails only when something reaches the container outside the `bash` tool: a `text_editor` call, whose tool injection fails (`SandboxInjectionError`), or the scorer, whose first step runs its own command in the agent's container (`SandboxUnavailableError`, which the scorer passes on). D60's "Inspect raises `SandboxUnavailableError`" describes where the attempt ends, not the first call that meets the dead container.
- **Effect on E6:** none on the outcome. A killed container is still retried as an infrastructure failure and never scored, because the scorer always reaches the agent's container first and raises. An agent that only uses `bash` may spend turns on tool errors before that happens, which costs time and does not change any record.
- **Tests:** both kill tests check that the retry's error says the sandbox is not running. The E4-across-a-retry test uses the real scorer, so the retry comes from the scorer, as it would in the full run. An earlier version used a no-op scorer and passed only because a broken helper raised an `AttributeError`; fixed before review.

### D80. One attempt of the full run retried after a test session removed its containers

- **Recorded:** 2026-11-25, Phase 5, during the full run.
- **What happened:** while the run was going, a `pytest` session ran from a second checkout of this repo. Its tests used no Docker, but `tests/conftest.py`'s session-end check force-removes every `evalh-*` and `inspect-evalh-*` container it finds, and it removed containers of the run's `delete-test` eval as its first attempts started. One attempt, `delete-test` on `queue-004`, epoch 1, failed in `docker compose up` ("No such container") and Inspect retried it once in a new sandbox (`retry_on_error`, design §8). Its final record is like the other 19 `delete-test` attempts: reward −1 with `protected_path`. No other attempt in the logs has a retry or an error, and none is excluded.
- **Decision:** by the owner, the run is kept and not redone. The report's one "attempt retried after an infrastructure failure" is this attempt.
- **Follow-up:** the session-end cleanup should remove only containers that appeared during its own session, so a test run can never break a concurrent eval. Until then, no test runs while `make eval` runs.

## Open questions

None recorded yet.
