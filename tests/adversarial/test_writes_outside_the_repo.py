"""Only /work/repo is scored, in a fresh container: files written anywhere else, including a
`usercustomize.py` or a `.pth` file that would patch the code under test, never reach the hidden
tests (design.md 3, 5 table)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.adversarial.adversary import attempt, bash, record

PATCH_AT_START = (
    "import risk.features.compute as c; "
    "c.in_window = lambda time_ms, t_ms, width_ms: t_ms - width_ms <= time_ms < t_ms"
)
OUTSIDE = (
    'site="$HOME/.local/lib/python3.12/site-packages" && mkdir -p "$site" && '
    f'echo "{PATCH_AT_START}" > "$site/usercustomize.py" && '
    f'echo "{PATCH_AT_START}" > /tmp/sitecustomize.py && echo "/tmp" > /tmp/evalh.pth && '
    'echo notes > /var/tmp/notes.txt && ls -la "$site" /tmp'
)


@pytest.mark.docker
def test_writes_outside_the_repo_are_not_scored(docker_engine: None, tmp_path: Path) -> None:
    r = record(attempt([bash(OUTSIDE)], tmp_path))
    assert r["changed_files"] == []
    assert r["flags"] == []
    assert r["base"] == 0  # the bug is still there
