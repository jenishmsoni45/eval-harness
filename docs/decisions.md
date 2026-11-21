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

## Open questions

None recorded yet.
