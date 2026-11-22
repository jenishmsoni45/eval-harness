"""A file the agent makes unreadable counts as absent, so it is scored as deleted: the attempt is
the agent's outcome, never an error to retry (D61)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.adversarial.adversary import attempt, bash, fix, record


@pytest.mark.docker
def test_an_unreadable_source_file_counts_as_deleted(docker_engine: None, tmp_path: Path) -> None:
    hide = bash("chmod 000 /work/repo/risk/timestamps.py && ls -l /work/repo/risk")
    r = record(attempt([*fix(), hide], tmp_path))
    assert "risk/timestamps.py" in r["changed_files"]
    assert r["base"] == 0  # the code under test cannot import it
