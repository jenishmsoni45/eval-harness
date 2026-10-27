# Project 5: Agent-evaluation harness and RL environments

> Realistic coding tasks for LLM agents, built from bugs planted in your own projects. They run in locked-down containers, are graded by hidden tests, are checked for reward hacking, and are reported with honest statistics. The same tasks are exposed as RL environments. No AI model runs anywhere: the agents are scripted programs with known success rates, which proves the harness measures correctly.

| | |
|---|---|
| **Wave** | Wave 2 |
| **Dates** | Phase 0 before Feb 22 · build Feb 22–Mar 28 |
| **Built for** | Anthropic (Fellows), OpenAI (Residency), Cohere, Shopify ML; also a strong answer to "how do you evaluate AI output?" anywhere |
| **Stack** | Python 3.12, uv, Inspect (`inspect_ai`, with `mockllm` for scripted agents), Docker, numpy/scipy, pandas, pytest + Hypothesis, pip-audit |
| **Install** | Docker Desktop, uv, git, gh |
| **Depends on** | Code from projects 1–4: the eval tasks are bugs planted in it |
| **Cost** | Free. No AI model is downloaded, run or called. |

---

## 1. What you're building

Anthropic's Fellows posting lists building RL environments and evaluating LLMs. Cohere and Shopify's ML internships point the same way. Labs hire people who can *measure* models, not wrap them.

What makes it stand out:
- **Reward-hacking detection.** It catches agents that edit or delete tests instead of fixing the bug, and scripted "cheater" agents prove the checks work.
- **Honest statistics:** confidence intervals and paired comparisons instead of one leaderboard number.
- **Tasks that double as RL environments,** with a reward that can't be gamed by touching tests.
- **Built on Inspect,** the UK AI Security Institute's eval framework. It runs agents in Docker sandboxes with networking switched off. Its `mockllm` provider takes a Python function in place of a model, which is how the scripted agents plug in, so a real model can replace them later with one setting.

**Why scripted agents work here:** each scripted agent has a success rate you set for each level of the task bank's **difficulty ladder** (easy, medium, hard), for example by applying the reference fix with a fixed probability. Because the true rate is known, the report can show the harness measures it correctly: the confidence intervals cover the true rate, and the paired comparison separates agents whose rates really differ. That proof is the result, and it carries over unchanged when a real model is plugged in.

## 2. Scope

**In**
- 10 eval tasks first, growing to 30 if time allows. Each has a container image, instructions, visible tests, hidden tests and a reference fix.
- A task validator: the broken repo fails the hidden tests, and the reference fix passes them every time.
- A hardened sandbox: no network; CPU, memory and time limits; a clean filesystem per attempt; hidden tests copied in only at scoring time.
- A model-agnostic agent with a small tool set (run a command, read a file, write a file), with step and time limits, and every step logged.
- Integrity checks, plus scripted cheater agents that prove they work.
- Statistics: pass@k, bootstrap confidence intervals over tasks, paired model comparisons, per-task variance.
- A report comparing 3 scripted agents of different skill, checking each measured rate and interval against the agent's true rate.
- An RL environment interface (reset, step, reward).

**Optional side quest:** a fix or docs improvement for Inspect, prepared in your fork; you submit it yourself. Alternatively, list the eval in the Inspect Evals register (that repo only takes PRs from pre-approved contributors).

**Out of scope:** any AI model (local or hosted), training a model, GPU tasks, a web dashboard, your own orchestrator or container runtime, and claims about what real models can do.

## 3. Architecture (starting sketch; Phase 0 turns it into Mermaid diagrams)

```
task_bank/<id>/ (image + instructions + visible tests)        hidden_tests/ + solution.patch (kept outside the image)
        │                                                              │
        ▼                                                              │
Inspect eval ──▶ Docker sandbox (no network, limits, clean FS) ◀── agent loop (bash/read/write, limits)
        │                         │ trajectory logged                         ▲
        │                         ▼                                           │ scripted agents via mockllm (known success rates) + cheaters
        │                scorer: hash protected files → copy hidden tests in → run → result
        │                         │
        │                integrity checks: tests edited? visible pass + hidden fail? protected paths touched?
        ▼                         ▼
   Inspect logs ──▶ stats (pass@k, bootstrap CI, paired diff) ──▶ report
                     RL env: reset() → instructions + repo · step(tool call) → observation · reward at end
```

**Eval-task format** (Phase 0 specifies it in `docs/task-spec.md`):
```
task_bank/ledger-007/
├── task.yaml          id, source project, bug category, difficulty, time limit, protected paths
├── instructions.md    what the "user" reports (a symptom, not the fix)
├── Dockerfile         builds the repo snapshot with git history stripped
├── repo/              code with the planted bug + visible tests
├── hidden_tests/      used only by the scorer
└── solution.patch     the reference fix
```

**Reward (RL interface):** the fraction of hidden tests passing, minus a penalty if any protected path changed. Editing tests must never raise the reward.

## 4. Guarantees and numbers

| # | Invariant | How it's tested |
|---|---|---|
| E1 | Every task is valid: the bug fails the hidden tests, and the reference fix passes them in N of N runs. | `make validate` in CI for every task |
| E2 | The agent can't reach the network. | A probe inside the sandbox tries DNS and HTTP and must fail |
| E3 | The agent never sees hidden tests or the fix. | A scripted agent searches the filesystem, `git log`, env vars and image layers |
| E4 | Each attempt starts from a clean filesystem. | Two attempts in a row; the second can't see the first's files |
| E5 | Every scripted cheater is flagged; no reference fix is flagged. | Cheaters that edit tests, delete tests, hard-code outputs or skip tests |
| E6 | Infrastructure failures are retried and never counted as agent failures. | Fault-injected runs (container start failure, container killed mid-attempt) |
| E7 | The statistics are correct. | pass@k vs brute force on small cases; bootstrap coverage checked in simulation |
| E8 | Reward never exceeds the hidden-test pass fraction, and touching protected files always lowers it. | Property test on the reward function |

**Numbers to publish:**
- Number of validated tasks per difficulty level
- pass@1 per agent with a 95% confidence interval and whether it covers the agent's true rate, plus the paired difference with its interval
- The share of apparent passes flagged by integrity checks (zero is a result too)
- Infrastructure-failure rate, median steps and wall time per attempt, and total run time

## 5. Questions Phase 0 must settle

1. Which scripted agents (skill at each difficulty level, how they fail) and which true success rates, so the calibration check means something?
2. Which projects and files do bugs get planted in, and where do those repos live locally?
3. What makes a good task at each difficulty level (easy, medium, hard)?
4. How do visible and hidden tests differ, so that overfitting shows up?
5. How many tasks and attempts per task are needed to tell apart two agents whose true rates differ by a set amount? Do a rough power estimate within a run time you accept.
6. Bootstrap over tasks or over attempts, and why?
7. Which paths are protected? Is editing a test ever legitimate?
8. What reward shape and penalty size, and how could an agent still game it?
9. What per-attempt limits (time, steps, CPU, memory), and how many sandboxes run at once within Docker's memory cap?
10. Inspect side quest: yes or no?

## 6. Phases

Each phase is one PR. Phase 0 writes the full acceptance criteria into `docs/phases.md`; these are the seeds.

| Phase | Target dates | Scope | Done when | Look closely at |
|---|---|---|---|---|
| **0** Plan | Before Feb 22 | Questions answered; requirements, architecture (Mermaid), design, task spec, phases, decisions | No open questions; docs consistent | Task spec; power estimate; model choice |
| **1** Scaffold | Feb 22 | uv project, Inspect wiring with `mockllm`, Docker sandbox config (network off), Makefile, CI with a scripted agent, one example task | `make test` and `make validate` green in CI | No model is called anywhere |
| **2** Task format and first tasks | Feb 23–28 | Task loader, validator, first 3 tasks (one per difficulty), one scripted-agent run | E1 passes; a run log exists | How tasks are built; history stripping |
| **3** Sandbox and agent | Mar 1–7 | Limits, clean filesystem, agent tools, trajectory logs; grow to 10 tasks | E2–E4 pass; 10 tasks validated | Sandbox config; what the agent can see |
| **4** Integrity | Mar 8–14 | Protected-file hashing, visible-pass/hidden-fail detection, scorer that copies hidden tests in at the end, cheater agents | E5 passes with 0 false flags | Every integrity rule; cheater coverage |
| **5** Statistics and the run | Mar 15–21 | pass@k, bootstrap, paired difference, run estimator, the full scripted-agent run, report with the calibration check | E6, E7 pass; report rebuilds from logs | Statistical claims vs intervals |
| **6** RL interface and ship | Mar 22–28 | RL environment, demo episode, README, postmortem, talk outline | E8 passes; definition of done met | Reward function; README claims |

## 7. Repo layout (Phase 1 creates it)

```
project-5-eval-harness/
├── CLAUDE.md  PLAN.md  README.md  .github/pull_request_template.md
├── docs/        requirements.md  architecture.md  design.md  task-spec.md  decisions.md  phases.md  postmortem.md
├── task_bank/   <task-id>/ task.yaml  instructions.md  Dockerfile  repo/  hidden_tests/  solution.patch
├── harness/     eval.py (Inspect task)  agent.py  scorer.py  integrity.py  sandbox/compose.yaml
├── stats/       passk.py  bootstrap.py  report.py
├── rl/          env.py
├── scripts/     validate_tasks.py  estimate_run.py
├── tests/       invariants/  adversarial/  cheaters/
├── results/     logs/ (Inspect logs)  reports/
├── pyproject.toml  Makefile  .github/workflows/ci.yml
```

## 8. Prompts

Run `claude` inside this folder. The workflow rules live in `CLAUDE.md`, so the prompts stay short.

### P0 · Phase 0: plan (paste once)

```text
Start phase 0 (planning). Follow the Phase 0 rules in @CLAUDE.md: no code and no scaffolding.
1. Read @PLAN.md. Check Docker's memory and CPU limits with `docker info` (read-only). List every open question: start with section 5, then add anything ambiguous, missing or contradictory. Ask me in batches of up to 5, each with options, trade-offs and your recommendation. Wait for my answers before the next batch.
2. Record every question and answer in docs/decisions.md.
3. When nothing is open, write:
   - docs/requirements.md: users (a researcher comparing agents, an RL engineer, a reviewer who must trust the numbers), user stories with acceptance criteria, non-functional requirements with numbers, non-goals
   - docs/architecture.md: Mermaid diagrams for the components, one attempt from start to score (sequence), the task build and validation flow, and the RL episode
   - docs/task-spec.md: the eval-task format, difficulty levels, validation rules, protected paths
   - docs/design.md: invariants E1–E8, the statistics plan with the power estimate, the reward design, failure modes, alternatives rejected, prior art (Inspect, SWE-bench), test plan
   - docs/phases.md: phases 1–6 from PLAN.md section 6, each with scope, testable acceptance criteria, tests to add and out of scope
4. Review the docs as a skeptical research engineer: leakage paths, grading bugs, statistical claims the design can't support, anything needing an AI model, a paid service or an install on this Mac beyond the Install row. Fix them, and ask me if a fix needs a decision.
5. Create branch phase-0-plan, commit, push, and open a docs-only PR with the template. Then stop.
```

### P1 · Start a phase (every phase after 0)

```text
Start phase <N>. Follow the phase workflow in @CLAUDE.md: sync main and confirm earlier phase PRs are merged, branch, read the phase in @docs/phases.md, ask me before coding if anything is unclear, build the whole phase with tests, run lint, tests and validate, self-review the full diff and fix what you find, then push and open the PR with the template. Before a full eval run, show me the estimate and wait. Stop when the PR is open.
```

### P2 · Address my review

```text
I've reviewed PR #<n>. Read every comment (`gh pr view <n> --comments` and the inline comments via `gh api repos/{owner}/{repo}/pulls/<n>/comments`). Fix each one on the same branch, or explain why you disagree. Run the checks, push, and reply with a short list of comment → what changed. Don't merge.
```

### P3 · Explain a PR to me (while reviewing)

```text
Walk me through PR #<n> as if onboarding me to code I must defend in a research-engineering interview. Follow the review-guide order. For each file: what it does, why it's built this way, the alternative rejected, and how the tests prove it. For any new eval task, explain the bug, why the hidden tests catch it, and how an agent could try to cheat. Then ask me 5 questions about it, one at a time, and correct what I get wrong. Don't change any code.
```

### P4 · Mock interview (after phase 6)

```text
Act as a research engineer interviewing me for Anthropic's Fellows program. Interview me about this project for 30 minutes, one question at a time. Start with "walk me through it", then go deep wherever my answer is vaguest: task validity, leakage, what the confidence interval assumes, reward hacking, how these tasks would become RL training data. Use @PLAN.md section 9 and @docs/decisions.md as a starting point and follow up on my answers. Don't give me answers. At the end, score clarity, depth and ownership out of 5, and list 3 topics to study.
```

### P-OSS · Inspect side quest (optional)

```text
I've forked and cloned UKGovernmentBEIS/inspect_ai at <path>. Read its contributing guide and check its rules on AI-assisted contributions. Find 3 small, real contributions (open issues, or problems I hit in this project: <describe>), ranked by how likely they are to be accepted. After I pick one, make the change on a branch in my fork with tests, run the repo's checks, and explain it file by file so I can review it. Don't open a PR or issue upstream; I'll submit it myself.
```

## 9. Finish line

**Definition of done** (after phase 6)
- [ ] Phase 0 docs merged and kept current, including the task spec and the power estimate
- [ ] E1–E8 run in CI with scripted agents only
- [ ] `make report` regenerates every README number from saved logs
- [ ] `docs/postmortem.md` on one real bug found during the build (a leak or a grading bug makes the best one)
- [ ] 3-minute demo video (a cheater caught; a report with intervals) + 20-minute talk outline
- [ ] README section on how Claude Code built the harness and the eval tasks under your plan and review, and how you verified them

**Resume line** (fill in from your own measurements, including zero):
> Built N containerized agent tasks on Inspect with hidden-test grading, reward-hacking checks and bootstrap confidence intervals, and exposed them as RL environments. Validated the statistics against scripted agents with known success rates (95% intervals covered the true rate in X% of runs); integrity checks flagged Y of M scripted cheaters with Z false flags.

**Questions to be ready for**
- How do you know a task is fair and not flaky?
- What does your confidence interval assume?
- How do you stop an agent escaping the sandbox?
- Why scripted agents, and what changes when a real model is plugged in?
- How would you shape the reward so an agent can't game it?
- Why build on Inspect instead of writing your own harness?
