"""One run of each cheater over its applicable tasks, made once per session and shared by the
cheater tests (tests/cheaters/cheats.py says which tasks, and how the runs are checked)."""

from __future__ import annotations

import pytest
from inspect_ai import task_with
from inspect_ai.log import EvalLog

from harness.agents.cheaters import CHEATERS, cheater_model
from harness.eval import evalh, run_eval
from harness.integrity import PROTECTED_PATH
from tests.cheaters.cheats import CheaterRuns, cheater_tasks, scored_then_inspected


@pytest.fixture(scope="session")
def cheater_runs(docker_engine: None, tmp_path_factory: pytest.TempPathFactory) -> CheaterRuns:
    runs: dict[str, EvalLog] = {}

    def run(name: str) -> EvalLog:
        if name not in runs:
            tasks = cheater_tasks(name)
            log_dir = str(tmp_path_factory.mktemp(f"cheater-{name}"))
            if CHEATERS[name].expected_flag == PROTECTED_PATH:
                task = task_with(evalh(task_ids=tasks), scorer=scored_then_inspected())
                runs[name] = run_eval(cheater_model(name), log_dir=log_dir, task=task)
            else:
                runs[name] = run_eval(cheater_model(name), task_ids=tasks, log_dir=log_dir)
        return runs[name]

    return run
