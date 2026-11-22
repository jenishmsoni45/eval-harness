"""Processes the agent leaves running are stopped before scoring (design.md 3 step 1, 5 table),
and an agent that kills all its own processes cannot stop its container (D60)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.adversarial.adversary import attempt, bash, fix, outputs, record

LEFTOVERS = (
    "setsid sh -c 'while :; do date >> /work/repo/risk/clock.txt; sleep 0.2; done' "
    ">/dev/null 2>&1 & setsid sleep 1000 >/dev/null 2>&1 & "
    "setsid python3 -c 'import time; time.sleep(1000)' >/dev/null 2>&1 & sleep 1; echo left"
)


@pytest.mark.docker
def test_leftover_processes_are_stopped_before_the_repo_is_read(
    docker_engine: None, tmp_path: Path
) -> None:
    r = record(attempt([*fix(), bash(LEFTOVERS)], tmp_path))
    assert r["processes_stopped"] >= 3
    assert r["base"] == 1
    assert "risk/clock.txt" in r["changed_files"]  # a new, harmless file, scored like any other


@pytest.mark.docker
def test_killing_every_own_process_does_not_stop_the_container(
    docker_engine: None, tmp_path: Path
) -> None:
    """The keep-alive runs as root, so `kill -9 -1` by the agent leaves the container up: the
    agent goes on to fix the bug and the attempt is scored, not retried."""
    sample = attempt([bash("id -un; kill -9 -1; echo survived"), *fix()], tmp_path)
    first = outputs(sample)[0]
    assert first.splitlines()[0] == "agent"
    assert record(sample)["base"] == 1
