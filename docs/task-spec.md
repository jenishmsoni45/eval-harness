# Eval-task specification

The format every eval task follows, how difficulty is assigned, which paths are protected, and the rules a task must pass before it is used. Decisions are in [`decisions.md`](decisions.md).

## Terms

- **Task:** one planted bug in a trimmed snapshot of a source project, with instructions, tests and patches.
- **Bank:** the set of validated tasks used for a run.
- **Attempt:** one agent working on one task once, from a clean container to a score.
- **Visible tests:** tests shipped in the repo the agent sees.
- **Hidden tests:** tests the agent never sees; copied into the scoring container only at scoring time.
- **Bug test:** a hidden test that fails on the shipped bug and passes with the reference fix.
- **Regression test:** any test, visible or hidden, that passes on the shipped bug and with the reference fix. Regression tests run from pristine copies at scoring time.
- **Canary string:** a fixed marker defined once in `task_bank/CANARY`, carried by every file the agent must never see.

## Directory layout

```
task_bank/
├── CANARY                     the canary string (one line)
└── <task-id>/
    ├── task.yaml              metadata, commands, protected paths (never in the image)
    ├── instructions.md        the symptom, in the user's words
    ├── Dockerfile             builds the task image; sits outside the build context
    ├── repo/                  the build context: snapshot with the planted bug + visible tests
    ├── hidden_tests/          hidden tests, laid out by their path inside the repo
    ├── solution.patch         the reference fix
    ├── wrong.patch            a plausible fix that passes visible tests and fails a bug test
    └── partial.patch          a fix that passes some but not all bug tests
```

Only `repo/` is the build context (D26). `task.yaml`, `instructions.md`, `hidden_tests/` and the three patches never enter an image. The harness gives `instructions.md` to the agent as its first message.

## Task ids

`<project>-<NNN>`, where `<project>` is `risk` (project 2, Python), `queue` (project 3, Go) or `vault` (project 4, Rust), and `NNN` is a three-digit sequence per project. Example: `risk-001`. Ids are never reused.

## `task.yaml`

```yaml
id: risk-001
canary: "<contents of task_bank/CANARY>"
source:
  project: risk-engine                      # risk-engine | job-queue | vaultline
  repo: https://github.com/jenishmsoni45/risk-engine
  commit: <full 40-character SHA>           # the commit the snapshot was taken from
  paths: [risk/rules/, tests/unit/rules/]   # what was copied, relative to the source repo
language: python                            # python | go | rust
difficulty: easy                            # easy | medium | hard (rules below)
hard_reason: null                           # required for a hard task fixed in one file
category: boundary                          # free-text bug category; does not set difficulty
visible_tests:
  command: [pytest, -p, no:cacheprovider, tests/visible]
hidden_tests:
  bug_tests:                                # run one at a time; each must fail on the bug
    - tests/hidden/test_window.py::test_window_includes_upper_edge
    - tests/hidden/test_window.py::test_window_property_seeded
  regression:
    command: [pytest, -p, no:cacheprovider, tests/visible, tests/hidden/regression]
    count: 0                                # number of regression tests that must run and pass
protected_extra: []                         # task-specific protected paths on top of the defaults
```

Rules:
- Every field is required; `hard_reason` and `protected_extra` may be null or empty.
- Commands are argument lists run in `/work/repo` without a shell.
- `bug_tests` uses the runner's own test identifiers: pytest node ids for Python, `<package>:<TestName>` for Go, `<test target>:<test name>` for Rust.
- `regression.count` is the exact number of regression tests the runner reports as run and passed with the reference fix; the validator checks it, and the scorer treats a different count as a regression failure (this catches skipped tests).
- No limit overrides: every task uses the limits of D21.

## `instructions.md`

- Describes the symptom as a user would report it: what they did, what they expected, what happened.
- Never names the fix. On easy tasks it may name the function where the symptom shows; on medium and hard tasks it describes behaviour only.
- Never mentions hidden tests, patches or the canary.
- The harness prepends a fixed preamble, the same for every task: the repo is at `/work/repo`; how to run the visible tests; tests and test or build configuration must not be changed; there is no network; when finished, call submit.
- Checked in review: whether the wording leaks the fix location on medium and hard tasks.

## Images

- **Base images**, one per language, are built from `images/<language>/Dockerfile` and named `evalh-base-<language>:<content hash>`. Each starts from an official, multi-architecture, glibc-based image pinned by digest (D20, D27), and adds the toolchain, `git`, `find`, `tar`, and a non-root user `agent`.
- **Task images** are built with `docker build -f task_bank/<id>/Dockerfile task_bank/<id>/repo` and named `evalh-task-<id>:<content hash>`. The content hash covers the build context, the Dockerfile and the base image digest.
- A task `Dockerfile` starts `FROM` its language's base image, copies the build context to `/work/repo` owned by `agent`, installs the snapshot's dependencies from its lockfile so tests run offline, warms the build cache by building the tests once, and creates a fresh git repository at `/work/repo` with exactly one commit of the shipped snapshot, so agents can use `git diff` without any source history.
- Offline settings per language: Python dependencies in a virtual environment installed from hashes; Go with `GOFLAGS=-mod=readonly`, `GOPROXY=off` and a warm module and build cache; Rust with `CARGO_NET_OFFLINE=true` and a warm `target/` directory.
- Images are built before an eval or validation run; the compose file references them by name with `pull_policy: never`.

## `repo/`: the snapshot

- A trimmed copy of the source project at `source.commit`: only the package under test, what it needs to build, its tests and its lockfile (D2). No `.git` directory, no CI files, no secrets, no benchmarks or fuzz targets.
- The planted bug is the only intended change from the source commit, apart from trimming, moving bug-catching tests out of the visible set, and removing references to files outside the snapshot (D89).
- **Visible tests** are the project's existing tests for the snapshot, minus every test that catches the bug, plus one failing reproduction test on easy tasks only (D4).
- **Rust:** visible tests live in `tests/` only (D9). Existing `#[cfg(test)]` unit tests in `src/` may stay; they are protected by the diff check.

## `hidden_tests/`

- Laid out by destination path inside the repo; the scorer copies each file to that path in the scoring container.
  - Python: `tests/hidden/…`
  - Go: `<package dir>/zz_hidden_<n>_test.go`, in the package under test
  - Rust: `tests/hidden_<n>.rs`, each its own test target

  Every destination lies inside a protected path, so a file the agent places there in advance is dropped before scoring and cannot shadow a hidden test.
- **Bug tests** check the fixed behaviour on inputs and edge cases that do not appear in the visible tests (D4). Existing tests that catch the bug move here as bug tests.
- **Regression tests** include the full existing suite that passes on the bug (the visible tests are run from pristine copies) plus any new hidden regression tests.
- **Determinism:** fixed seeds for any randomness (Hypothesis with `derandomize=True` and no example database, `proptest` with a fixed seed and no persisted failures, Go with `-count=1` and seeded generators), no wall clock, no network, no dependence on test order (D12).
- Every hidden-test file contains the canary string in a comment.
- Checked in review: that no hidden bug-test input appears verbatim in the visible tests. The hard-code cheater (D13) also checks this on easy tasks.

## Patches

All three are unified diffs relative to `repo/`, touch no protected path, contain the canary string in a header comment, and apply cleanly.

| Patch | Must |
|---|---|
| `solution.patch` | Make every visible, bug and regression test pass |
| `wrong.patch` | Make every visible test pass, every regression test pass, and at least one bug test fail |
| `partial.patch` | Make every regression test pass, and at least one but not all bug tests pass |

Scripted agents read these patches on the host and apply them through their normal tools (D14); this is a test fixture standing in for a model's skill, not a leak.

## Difficulty levels

Difficulty follows how hard the bug is to locate and how large the fix is (D3). "Changed lines" means lines added plus lines removed in `solution.patch`.

| Level | Instructions | Fix | Visible tests on the shipped bug | Checked by |
|---|---|---|---|---|
| **easy** | May name the function where the symptom shows | 1 file, ≤ 5 changed lines | At least one fails | Validator |
| **medium** | Symptom only | 1 file, ≤ 20 changed lines, away from where the symptom shows | All pass | Validator (file count, lines, visible results); review (location) |
| **hard** | Symptom only | ≥ 2 files, or 1 file with `hard_reason` explaining the invariant that must be understood | All pass | Validator (files, `hard_reason`, visible results); review (the reason) |

## Protected paths

A change to a protected path is dropped before scoring and sets the `protected_path` cheat flag (D9, D10, D28). Paths are matched relative to `/work/repo`; the defaults apply to every task of the language, plus `protected_extra`.

| Language | Default protected paths |
|---|---|
| All | Every visible test file; any new or changed `conftest.py`, `sitecustomize.py`, `usercustomize.py`, `*.pth`; `Makefile`; `.git/` is ignored, not protected |
| Python | `tests/**`, `pyproject.toml`, `pytest.ini`, `setup.cfg`, `tox.ini`, `uv.lock` |
| Go | `**/*_test.go`, `go.mod`, `go.sum` |
| Rust | `tests/**`, `Cargo.toml`, `Cargo.lock`, `build.rs`, `.cargo/**`, and any change inside a `#[cfg(test)]` item in `src/**` |

Ignored entirely, never compared and never scored: `.git/`, `__pycache__/`, `.pytest_cache/`, `.hypothesis/`, `target/`, `*.pyc`. Symlinks and files outside `/work/repo` are never scored; an attempt whose changes include a symlink is flagged `diff_rejected`.

## Validation rules

`make validate` checks every rule below for each task; a task is used only when all pass (E1). Runs marked "×5" are repeated 5 times in fresh containers with consistent results (D12).

| # | Rule |
|---|---|
| V1 | `task.yaml` matches the schema; the id matches the directory; the canary matches `task_bank/CANARY` |
| V2 | The task image builds from `repo/` alone, and the visible tests run with the network off |
| V3 | The image contains no source history: `/work/repo/.git` has exactly one commit whose tree equals the shipped snapshot, and there is no other `.git` directory |
| V4 | No hidden-test content, patch content, `task.yaml` or canary string is in the build context, in `docker history --no-trunc`, or anywhere in a container of the image (D26) |
| V5 | Shipped bug ×5: each bug test, run on its own, fails; every regression test passes and the count equals `regression.count` |
| V6 | Reference fix ×5: every visible test, bug test and regression test passes, with the expected regression count |
| V7 | Wrong patch ×5: visible tests pass, regression tests pass, at least one bug test fails, and the same bug tests fail each time |
| V8 | Partial patch ×5: regression tests pass, at least one but not all bug tests pass, and the same ones each time |
| V9 | Difficulty: the label matches the table above (files and changed lines of `solution.patch`, `hard_reason`, visible results on the shipped bug) |
| V10 | No patch touches a protected path, and every hidden-test destination lies inside a protected path |
| V11 | The runner-detection check sets no flag on any of the three patches (from Phase 4) |
| V12 | Every hidden-test file and patch carries the canary string |
| V13 | With the reference fix, the full scoring run (bug tests one at a time plus the regression suite) finishes within half the 5-minute scoring limit |

## Language specifics

| | Python | Go | Rust |
|---|---|---|---|
| Source project | risk-engine (project 2) | job-queue (project 3) | vaultline (project 4) |
| Run one bug test | `pytest -p no:cacheprovider <node id>` | `go test -count=1 -run '^<Name>$' ./<package>` | `cargo test --offline --test <target> -- --exact <name>` |
| Pass / fail | Exit code 0 / non-zero; exit code 5 (nothing collected) is a fail | Exit code 0 / non-zero; "no tests to run" is a fail | Exit code 0 / non-zero; "0 passed" is a fail |
| Regression count from | `--junitxml` report | `go test -json` events | the `test result:` summary lines |
