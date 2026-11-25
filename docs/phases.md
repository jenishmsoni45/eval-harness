# Phases

One phase, one pull request. Each phase lists its scope, acceptance criteria (each one testable, and each one ticked in the PR with the code and test that prove it), the tests it adds, and what is out of scope. Every phase also passes `make lint`, `make test`, `make audit` and `make validate`. The owner starts each phase; schedule targets are in `PLAN.md`.

Decisions are `D<n>` in [`decisions.md`](decisions.md); invariants, sections and tests are in [`design.md`](design.md); validation rules `V<n>` are in [`task-spec.md`](task-spec.md).

---

## Phase 1: Scaffold

**Scope**
- uv project (`pyproject.toml`, `uv.lock`) on Python 3.12 with exact pins: `inspect_ai`, numpy, scipy, pandas, PyYAML, pytest, Hypothesis, ruff, mypy, pip-audit. Each dependency justified in the PR.
- `Makefile` with `lint` (ruff and mypy), `test`, `audit`, `validate` and `power`.
- `images/python/Dockerfile` (official image pinned by digest) and `task_bank/CANARY`.
- One example task, `risk-001` (Python, easy, from risk-engine), complete enough for a minimal validation: shipped bug fails each bug test and reference fix passes, 5 of 5. It becomes a full-spec task in Phase 2.
- `harness/eval.py`:
  - an Inspect task named so its compose projects are `inspect-evalh-…` (D25);
  - the `react()` agent with `bash` and `text_editor`, `attempts=1` (no mid-attempt scoring feedback), `parallel_tool_calls=False` and `max_samples=3`;
  - the setup solver that writes the task id and epoch to `store()`;
  - the two-service compose template with `network_mode: none` and the D21 limits;
  - `retry_on_error=2` and `fail_on_error=0.05`.
- `harness/agents/`: the oracle agent as a `mockllm` callable that applies `solution.patch` through `text_editor`.
- A minimal scorer: copy the agent's changed files into the scorer container, copy the hidden tests in, and compute `base` (D11). Integrity checks come in Phase 4.
- `scripts/power_estimate.py`, which writes the power and coverage table into `design.md` §7.7 (D8).
- CI (D15): `.github/workflows/ci.yml` on every PR (lint, test, audit, validate changed tasks) and `.github/workflows/validate-all.yml` run by hand; both with read-only permissions.

**Acceptance criteria**
- P1-1. `uv sync --frozen` installs exact versions from `uv.lock`; `make lint`, `make test` and `make audit` pass locally and in CI.
- P1-2. `make validate` builds `evalh-base-python` and `evalh-task-risk-001`, and shows the shipped bug failing each bug test and the reference fix passing all hidden tests in 5 of 5 runs, locally (arm64) and in CI (amd64).
- P1-3. The oracle agent, run through `mockllm` on `risk-001`, ends with `base` 1; the log shows `bash` and `text_editor` calls and the model `mockllm/…`.
- P1-4. No model is called anywhere: `test_no_model.py` passes.
- P1-5. Every compose service has `network_mode: none` and every D21 limit: `test_compose.py` passes.
- P1-6. Each D27 assumption is confirmed by `test_inspect_assumptions.py`: `store()` is readable from the `mockllm` callable; `text_editor` works with the network off on arm64 and amd64; no `inspect-evalh-*` container remains after a sample. If any fails, the phase stops for a decision.
- P1-7. `test_import_boundary.py` passes (R4).
- P1-8. `make power` writes the table between the markers in `design.md` §7.7, deterministically. The table shows strong-vs-mid power ≥ 0.80 and, for every agent, coverage of the population rate within [0.93, 0.99] at the D30 size (20 tasks × 6 attempts); if not, the phase stops and the run size is decided again.
- P1-9. After every `make` target, no `evalh-*` or `inspect-evalh-*` container remains (checked by a test fixture).

**Tests to add:** `test_no_model.py`, `test_import_boundary.py`, `test_compose.py`, `test_inspect_assumptions.py`, `test_power_estimate.py`, and a container-cleanup fixture.

**Out of scope:** Go and Rust images; the full validator; integrity checks; statistics beyond the power script.

---

## Phase 2: Task format and first tasks

**Scope**
- `task.yaml` schema and loader (task spec).
- `scripts/validate_tasks.py` with rules V1–V10, V12 and V13 (V11 arrives with the runner-detection check in Phase 4).
- `images/go/Dockerfile` and `images/rust/Dockerfile` (official images pinned by digest).
- Three full-spec tasks (D23): `risk-001` (Python, easy), `queue-001` (Go, medium) and `vault-001` (Rust, hard), each with `wrong.patch` and `partial.patch` (D14).
- One scripted run: the oracle agent on all three tasks.

**Acceptance criteria**
- P2-1. The loader rejects every malformed `task.yaml` case in `test_task_schema.py` with a message naming the field.
- P2-2. Each implemented validation rule has a test with a deliberately broken fixture task that the rule rejects.
- P2-3. The three tasks pass `make validate` locally (arm64) and in CI (amd64).
- P2-4. V3: no image contains source history; each image's git repository has exactly one commit whose tree equals the shipped snapshot.
- P2-5. V4: no hidden material in any build context, `docker history --no-trunc` output, or container filesystem.
- P2-6. The oracle run on all three tasks writes an Inspect log in which every attempt has `base` 1.
- P2-7. Each `task.yaml` records the source repo and full commit SHA; snapshots follow the trimming rules (checked in review).
- P2-8. PR CI validates only the tasks a PR changes; the "validate all" workflow validates all three.

**Tests to add:** `test_task_schema.py`, a validator rule test per rule, `tests/invariants/test_e1_validity.py`.

**Out of scope:** limits and hardening beyond Phase 1; strong, mid and weak agents; cheaters.

---

## Phase 3: Sandbox and agent

**Scope**
- Full sandbox hardening and limits (design §2): non-root user, dropped capabilities, `no-new-privileges`, process, CPU and memory limits, the turn, time and scoring limits.
- Per-attempt record in the log (R5): tool calls, wall time, limit hit.
- Strong, mid and weak scripted agents (D5, design §6): seeding, per-task true rates, failure modes, and the true rate written to metadata.
- The network probe agent (E2) and the snoop cheater as the leakage probe (E3).
- Grow the bank to 10 validated tasks, at least 3 per difficulty level and at least 2 per language.

**Acceptance criteria**
- P3-1. E2 holds: `test_e2_network.py` passes.
- P3-2. E3 holds on every task: `test_e3_leakage.py` passes.
- P3-3. E4 holds: `test_e4_clean_fs.py` passes.
- P3-4. Each limit (30 turns, 10 minutes, 5-minute scoring) ends an attempt in a test, and the log records which limit was hit.
- P3-5. For a fixed seed, every scripted agent makes the same choices on a rerun; each failure mode gives its expected `base` (wrong patch below 1, partial patch strictly between 0 and 1, give-up 0, out of steps 0); true rates follow design §6.
- P3-6. 10 tasks pass `make validate`, with the stated level and language spread.

**Tests to add:** `test_e2_network.py`, `test_e3_leakage.py`, `test_e4_clean_fs.py`, `test_limits.py`, `test_scripted_agents.py`.

**Out of scope:** integrity flags and the full scoring pipeline; statistics.

---

## Phase 4: Integrity

**Scope**
- The full scoring pipeline (design §3): stop the agent's processes; read the repo as a tar stream; compare with the host's snapshot; drop protected changes (including Rust `#[cfg(test)]`); apply the rest in the scorer container; per-test runs with the regression count check; reward and success per D28.
- `harness/integrity.py`: protected paths, runner-detection and snooping rules, the overfitting signal and `diff_rejected` (design §4); validation rule V11.
- The six cheaters (D13) for every language where each trick applies.
- Adversarial tests (design §5 table).
- Grow the bank to 15 validated tasks (D24).

**Acceptance criteria**
- P4-1. E5: every cheater's attempt on every applicable task gets its expected flag (`tests/cheaters/`).
- P4-2. No cheat flag on any task's reference, wrong or partial patch (V11), nor on any honest scripted agent's trajectory; the oracle replay gets no flag at all.
- P4-3. Protected changes never reach the scorer container (a test inspects it after the edit-test cheater).
- P4-4. A regression count that differs from `regression.count` gives `base` 0 (a test with tests skipped from source).
- P4-5. Every adversarial test passes.
- P4-6. Unit tests show the reward of every flagged attempt follows D28.
- P4-7. 15 tasks pass `make validate`.

**Tests to add:** `test_protected_paths.py`, `test_runner_detection.py`, `test_snooping.py`, `tests/adversarial/`, `tests/cheaters/`, `tests/invariants/test_e5_no_false_flags.py`.

**Out of scope:** statistics; obfuscated cheater variants (a follow-up, D13).

---

## Phase 5: Statistics and the run

**Scope**
- `stats/passk.py`, `stats/bootstrap.py` and `stats/report.py` (design §7); `make report`.
- `scripts/estimate_run.py` and `make estimate`: counts attempts from the bank and the agents, and takes per-attempt wall time per language from a timed oracle run on one task per language; `make eval`.
- Fault injection for E6.
- Tasks 16–20, bringing the bank to its final composition (design §14).
- The full scripted run, after the owner approves the `make estimate` output; its logs committed to `results/logs/` (D19).

**Acceptance criteria**
- P5-1. E7 holds: `test_e7_stats.py` passes (exhaustive pass@k for n ≤ 8, the coverage band, bootstrap determinism).
- P5-2. E6 holds: `test_e6_infra.py` passes.
- P5-3. `make estimate` prints attempts, containers at once and expected wall time; the expected time is at most 6 hours (D22); the output is shown to the owner, and the run waits for approval.
- P5-4. 20 tasks pass `make validate`: 7 easy, 7 medium, 6 hard; 10 Python, 5 Go, 5 Rust.
- P5-5. The full run's logs are committed; excluded attempts are at most 5%, or the run is marked invalid.
- P5-6. `make report` rebuilds the report byte-for-byte from the committed logs. The report contains:
  - per-agent pass@1 with its 95% interval, and pass@k for k = 1 … 6, by level and language;
  - paired differences with intervals, worded per design §7.4;
  - the calibration check against bank and population rates;
  - integrity shares per flag;
  - infrastructure-failure rate, median steps, wall time per attempt and total run time.
- P5-7. The report refuses to present an invalid run as results (`test_report.py`).

**Tests to add:** `test_e7_stats.py`, `test_e6_infra.py`, `test_report.py`.

**Out of scope:** the RL interface; README numbers (Phase 6).

---

## Phase 6: RL interface and ship

**Scope**
- `rl/env.py`: `reset` / `step` / `close` over the same images, limits and scorer (architecture, RL episode).
- E8 property tests on the reward function.
- `harness/agents/demo_episode.py` and `make demo`: one episode with an honest scripted policy and one with a cheater, printing rewards (D85).
- `README.md` with every number generated by `make report`; `docs/postmortem.md` on one real bug found during the build; `docs/talk-outline.md`.
- PLAN.md §9's definition of done, except the demo video, which the owner records.

**Acceptance criteria**
- P6-1. E8 holds: `test_e8_reward.py` passes.
- P6-2. `test_rl_env.py`:
  - `reset` returns the instructions and repo listing;
  - no observation contains hidden-test names, content or output;
  - `step` handles every action type;
  - the reward equals the eval scorer's for the same changes;
  - `close` leaves no `evalh-*` container;
  - a scripted policy with the same seed gives the same trajectory and reward.
- P6-3. `harness/agents/demo_episode.py` runs both episodes; the cheater's reward is at most 0.
- P6-4. Every number in `README.md` sits in a block that `make report` writes; a test fails if the README block differs from a fresh `make report`.
- P6-5. `docs/postmortem.md` and `docs/talk-outline.md` exist and are complete.

**Tests to add:** `test_e8_reward.py`, `test_rl_env.py`, a README-numbers test.

**Out of scope:** the Inspect side quest (D16); any real model.
