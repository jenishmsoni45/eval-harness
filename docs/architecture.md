# Architecture

How the parts fit together. The format of a task is in [`task-spec.md`](task-spec.md); the reasoning behind each choice is in [`design.md`](design.md) and [`decisions.md`](decisions.md).

## Components

```mermaid
flowchart LR
  subgraph host["Host (this Mac or a CI runner)"]
    direction TB
    bank["task_bank/{id}/<br/>task.yaml · instructions.md<br/>Dockerfile · repo/"]
    secret["task_bank/{id}/<br/>hidden_tests/ · solution.patch<br/>wrong.patch · partial.patch"]
    images["images/{lang}/Dockerfile<br/>(base images)"]
    validate["scripts/validate_tasks.py"]
    eval["harness/eval.py<br/>(Inspect task)"]
    agents["harness/agents/<br/>scripted agents + cheaters<br/>(mockllm callables)"]
    scorer["harness/scorer.py"]
    integrity["harness/integrity.py"]
    logs[("results/logs/<br/>Inspect logs")]
    stats["stats/<br/>passk · bootstrap · report"]
    reports[("results/reports/")]
    rl["rl/env.py"]
    estimate["scripts/estimate_run.py<br/>scripts/power_estimate.py"]
  end

  subgraph docker["Docker Desktop (network_mode: none)"]
    direction TB
    agentbox["default service<br/>agent's container"]
    scorebox["scorer service<br/>fresh scoring container"]
  end

  images --> validate
  bank --> validate
  secret --> validate
  validate -->|"builds evalh-task-{id}"| docker
  bank --> eval
  eval -->|Inspect sandbox| agentbox
  eval --> agents
  agents -.->|reads patches on host| secret
  agents -->|bash · text_editor| agentbox
  eval --> scorer
  scorer -->|reads repo tree| agentbox
  scorer --> integrity
  scorer -->|"non-protected changes<br/>+ hidden tests"| scorebox
  secret --> scorer
  eval --> logs
  logs --> stats --> reports
  rl --> scorer
  rl -->|"evalh-rl-* project"| docker
```

| Component | Responsibility | Never does |
|---|---|---|
| `task_bank/` | One directory per task (task spec) | Put hidden material inside `repo/` |
| `images/` | One base image per language: toolchain, `git`, non-root `agent` user | Contain task code or tests |
| `scripts/validate_tasks.py` | Build task images and check validation rules V1–V13 | Use a task that fails any rule |
| `harness/eval.py` | The Inspect task: dataset of tasks × attempts, the `react()` agent with `bash` and `text_editor`, the sandbox config, limits, retries | Contain any scripted-agent logic |
| `harness/agents/` | Scripted agents and cheaters, as `mockllm` callables; the only code that reads patches | Get imported by any other harness module (R4) |
| `harness/scorer.py` | Take the agent's changes, drop protected ones, run hidden tests in the scoring container, compute reward and success | Run anything in the agent's container except reading the repo and stopping processes |
| `harness/integrity.py` | Protected-path, runner-detection and snooping checks; the overfitting signal | Change test results |
| `harness/sandbox/compose.yaml` | Template for the two services of a sample, with every limit and `network_mode: none` | Mount host paths or the Docker socket |
| `stats/` | pass@k, cluster bootstrap, paired differences, calibration check, report | Read anything but saved logs |
| `rl/env.py` | `reset` / `step` / reward over the same images, limits and scorer | Have its own reward logic |
| `scripts/estimate_run.py` | Attempts, containers at once, expected wall time | Start a run |
| `scripts/power_estimate.py` | Power and coverage simulation for the run size (D8) | Read logs |

## One attempt, from start to score

```mermaid
sequenceDiagram
  autonumber
  participant I as Inspect (harness/eval.py)
  participant D as Docker
  participant A as default container (agent)
  participant S as scorer container
  participant M as agent (mockllm callable)
  participant Sc as harness/scorer.py

  I->>D: compose up project inspect-evalh-i{random}<br/>(default + scorer, network none, limits)
  D-->>I: both containers running from evalh-task-{id}
  I->>I: setup solver writes task id and epoch to store()
  I->>M: instructions (preamble + instructions.md)
  loop at most 30 turns, one tool call each, 10 min wall
    M-->>I: tool call (bash or text_editor)
    I->>A: run tool
    A-->>I: output
    I->>M: conversation so far
  end
  M-->>I: submit (or a limit is hit)
  Sc->>A: stop the agent's processes, read /work/repo as a tar stream
  Sc->>Sc: compare with pristine repo/ on host<br/>drop protected changes, run integrity checks
  Sc->>S: write non-protected changed files
  Sc->>S: run visible tests (no hidden test in the container yet, D40)
  Sc->>S: copy hidden_tests/ in
  Sc->>S: run each bug test alone, then the regression suite (5 min in all)
  S-->>Sc: exit codes and counts
  Sc->>Sc: base reward, cheat flags, reward, success
  Sc-->>I: score + metadata (flags, counts, limit hit)
  I->>D: compose down --volumes (both containers removed)
  I->>I: write sample to results/logs/
```

If Docker fails to start a container or a container dies mid-attempt, Inspect records an error and retries the whole attempt in a new sandbox with the same seed, up to 2 times (D18). A command that times out or runs out of memory inside the agent's container is the agent's outcome and is not retried.

## Task build and validation

```mermaid
flowchart TD
  src["source repo at a pinned commit<br/>(risk-engine · job-queue · vaultline)"] -->|"trim, plant bug,<br/>split tests"| author["task_bank/{id}/"]
  author --> v1{"V1 schema<br/>and canary"}
  v1 -->|ok| base["build evalh-base-{lang}<br/>(official image by digest)"]
  base --> build["docker build -f Dockerfile repo/<br/>→ evalh-task-{id}:{hash}"]
  build --> v2{"V2 builds, visible tests<br/>run offline"}
  v2 --> v34{"V3 one-commit git only<br/>V4 no hidden material in<br/>context, history or filesystem"}
  v34 --> runs["×5 in fresh containers:<br/>V5 shipped bug · V6 reference fix<br/>V7 wrong patch · V8 partial patch"]
  runs --> v9{"V9 difficulty · V10 protected<br/>V11 runner check · V12 canary<br/>V13 scoring time"}
  v9 -->|all pass| ok["task is usable"]
  v1 -->|fail| reject["task rejected,<br/>reason printed"]
  v2 -->|fail| reject
  v34 -->|fail| reject
  runs -->|any inconsistency| reject
  v9 -->|fail| reject
```

## RL episode

```mermaid
sequenceDiagram
  autonumber
  participant P as policy
  participant E as rl/env.py
  participant D as Docker
  participant A as agent container
  participant S as scorer container
  participant Sc as harness/scorer.py

  P->>E: reset(task_id, seed)
  E->>D: compose up project evalh-rl-{random}<br/>(same template and limits as the eval)
  E-->>P: observation: instructions + repo listing
  loop until submit or a limit (30 steps, 10 min)
    P->>E: step(action)
    E->>A: run command / view / create / str_replace
    A-->>E: output
    E-->>P: observation, done=false, reward=None
  end
  P->>E: step(submit)
  E->>Sc: score(agent container, scorer container, task)
  Sc-->>E: reward, flags
  E-->>P: observation, done=true, reward
  P->>E: close()
  E->>D: compose down --volumes
```

The RL environment runs outside Inspect, so it starts its own compose project, named `evalh-rl-{random}` (D25), from the same template. It calls the same scorer through a small sandbox interface (`exec`, `read_file`, `write_file`) that both Inspect's sandbox and the environment's Docker wrapper provide, so the reward cannot drift from the eval's.

## Statistics and reporting

```mermaid
flowchart LR
  logs[("results/logs/*.eval")] --> load["load attempts:<br/>agent, task, epoch, reward,<br/>success, flags, retries"]
  load --> valid{"excluded attempts ≤ 5%?"}
  valid -->|no| invalid["report marks the run invalid"]
  valid -->|yes| passk["pass@k per task<br/>(unbiased estimator)"]
  passk --> boot["cluster bootstrap over tasks<br/>(seeded)"]
  boot --> ci["pass@1 with 95% interval<br/>per agent, level, language"]
  boot --> paired["paired differences<br/>with 95% intervals"]
  truth["true rates from D5<br/>+ per-task offsets"] --> calib["calibration: does each<br/>interval cover the true rate?"]
  ci --> calib
  load --> integ["integrity: share of apparent<br/>passes flagged, per flag"]
  load --> ops["infra-failure rate, median steps,<br/>wall time per attempt, run time"]
  ci --> report[("results/reports/")]
  paired --> report
  calib --> report
  integ --> report
  ops --> report
```

## Repo layout

```
project-5-eval-harness/
├── PLAN.md  README.md  Makefile  pyproject.toml  uv.lock
├── .github/   pull_request_template.md  workflows/ci.yml  workflows/validate-all.yml
├── docs/      requirements.md  architecture.md  design.md  task-spec.md  decisions.md  phases.md  postmortem.md
├── images/    python/Dockerfile  go/Dockerfile  rust/Dockerfile
├── task_bank/ CANARY  <task-id>/ (task spec)
├── harness/   eval.py  scorer.py  integrity.py  agents/  sandbox/compose.yaml
├── stats/     passk.py  bootstrap.py  report.py
├── rl/        env.py
├── scripts/   validate_tasks.py  estimate_run.py  power_estimate.py
├── tests/     unit/  invariants/  adversarial/  cheaters/
└── results/   logs/  reports/
```

This refines PLAN.md §7: `images/` holds the base images, `harness/agents/` holds the scripted agents, `scripts/power_estimate.py` comes from D8, `tests/unit/` holds unit tests, and `validate-all.yml` comes from D15.
