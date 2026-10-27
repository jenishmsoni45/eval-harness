# Project 5: Agent-evaluation harness and RL environments

An eval harness built on Inspect. Coding tasks made from bugs planted in my projects 1–4 run in locked-down Docker sandboxes, are graded by hidden tests and checked for reward hacking. Results are reported with bootstrap confidence intervals, and the tasks are exposed as RL environments. No AI model runs anywhere: the agents under test are scripted programs with known success rates, plus scripted cheaters, driven through Inspect's `mockllm` provider so a real model could replace them later.

## Source of truth

- Until the Phase 0 PR is merged, `PLAN.md` is the brief.
- After that, the docs are the source of truth: `docs/requirements.md`, `docs/architecture.md`, `docs/design.md`, `docs/task-spec.md`, `docs/decisions.md` and `docs/phases.md`. If code and docs disagree, the docs win. If the docs look wrong, stop and ask me.

## Workflow: one phase, one PR

I start every phase by name ("Start phase 3"). Never start a phase on your own.

1. **Sync.** `git checkout main && git pull`. Check with `gh pr list` that no earlier phase PR is still open. Create the branch `phase-<N>-<short-name>`.
2. **Read.** Read the phase in `docs/phases.md` and the docs it touches. If anything is ambiguous, missing or conflicts with the docs, ask me before writing code. Never invent requirements.
3. **Build the whole phase.** Write the code, a test for every acceptance criterion, and any doc updates the phase lists. Use small, logical commits with clear messages.
4. **Verify.** `make lint`, `make test`, `make audit` and `make validate` must pass, plus any check the phase names. Never skip, weaken or delete a test to get green; if a test is wrong, say so in the PR.
5. **Self-review.** Review `git diff main...HEAD` as a senior research engineer would. Check scoring correctness, leakage of hidden tests, statistical correctness, reproducibility, a test for each behaviour, and needless complexity. Fix what you find.
6. **Open the PR.** Push, then run `gh pr create` and fill in every section of `.github/pull_request_template.md`.
7. **Stop.** Send me the PR link and wait.

**When I ask you to address review comments,** read them with `gh pr view <n> --comments` and `gh api repos/{owner}/{repo}/pulls/<n>/comments`. Fix them on the same branch, run the checks, push, and reply with a list of what changed. Never merge.

## Phase 0 is planning only

Write no code and do no scaffolding. You may run read-only commands to answer planning questions, such as `docker info` to check Docker's memory and CPU limits. First ask me every open question: start with "Questions Phase 0 must settle" in PLAN.md, then add anything else unclear. Ask in batches of up to 5, each with options, trade-offs and your recommendation. Record every question and answer in `docs/decisions.md`. Only when nothing is open, write the Phase 0 docs listed in PLAN.md. Self-review them for gaps, contradictions and untestable criteria, then open a docs-only PR.

## Surprises mid-phase

If the design turns out to be wrong or a requirement can't be met, stop. Explain the problem and the options, then wait. Once I decide, record the decision in `docs/decisions.md` and continue. Out-of-scope ideas go under "Follow-ups" in the PR, not into the code.

## Hard limits

- Never push to `main`, merge a PR, force-push, or rewrite pushed history.
- I am the only author. Commits and PRs carry no `Co-Authored-By` trailer, no "Generated with Claude Code" line and no mention of Claude or AI in commit messages, PR titles or PR bodies.
- Free and local only, with no AI models. Never install, download or run a model (no Ollama, no model weights), never call a hosted model API, and never add API keys. Use no cloud service, paid API or sign-up. If something seems to need one, stop and ask.
- No secrets in the repo.
- Never install anything on this Mac: no `brew`, no global `pip` or `npm`, no `curl | sh`, no installers. Project dependencies through uv are fine. If a tool is missing, stop and ask me.
- Add only well-known, widely used dependencies and Docker images (official or verified publisher), pinned to exact versions in the committed lockfile and compose file. Justify each new one in the PR.
- Nothing keeps running after a command finishes: every sandbox container is removed when its attempt ends.
- Change `docs/requirements.md`, `docs/architecture.md`, `docs/design.md` or `docs/task-spec.md` only with my approval, and log each change in `docs/decisions.md`.
- Never put a number in `README.md` or `docs/` unless a script in the repo produced it.

## Project rules

- Before a full eval run, show the `make estimate` output (attempts, containers at once and expected wall time) and wait for my go-ahead.
- The agent under test must never be able to see hidden tests or reference fixes: not in the image, the git history, the environment or error messages. Strip git history from every task image.
- Report numbers come only from saved logs via `make report`. Never claim one agent beats another unless the paired interval excludes zero.
- Every eval task passes `make validate` before it's used: the bug fails the hidden tests, and the reference fix passes them every time.
- The optional Inspect contribution happens only in my fork. Never open a PR or issue on the upstream repo; I submit it myself.

## Stack and commands

- Python 3.12 (uv), inspect_ai (`mockllm` for scripted agents), Docker, numpy/scipy, pandas, pytest + Hypothesis, ruff, mypy, pip-audit
- `make validate` · `make test` · `make lint` · `make audit` (pip-audit on the locked dependencies) · `make estimate` · `make eval` (runs the scripted agents on every task) · `make report` (rebuilds reports from saved logs)

## Invariants the tests must enforce

1. Every eval task fails the hidden tests as shipped, and its reference fix passes them in N of N runs.
2. The sandbox has no network access.
3. The agent never sees hidden tests or the fix (filesystem, git history, env, image layers).
4. Every attempt starts from a clean filesystem.
5. Every scripted cheater is flagged; no reference fix is flagged.
6. Infrastructure failures are retried and never counted as agent failures.
7. pass@k and bootstrap code match brute force and simulation checks.
8. Reward never exceeds the hidden-test pass fraction, and touching protected paths always lowers it.
