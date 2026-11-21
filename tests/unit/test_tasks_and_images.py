"""Reading a task and naming its images (task-spec.md "task.yaml" and "Images")."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from harness.images import base_image_tag, task_image_tag
from harness.tasks import TASK_BANK, canary, load_task, read_tree, task_ids


def test_the_bank_holds_risk_001_and_it_loads() -> None:
    assert "risk-001" in task_ids()
    task = load_task("risk-001")
    assert (task.language, task.difficulty) == ("python", "easy")
    assert task.visible_command == ("pytest", "-p", "no:cacheprovider", "tests/visible")
    assert len(task.bug_tests) == 3
    assert task.regression_count > 0


def test_a_task_id_must_match_its_directory(tmp_path: Path) -> None:
    shutil.copytree(TASK_BANK / "risk-001", tmp_path / "risk-002")
    with pytest.raises(ValueError, match="does not match"):
        load_task("risk-002", bank=tmp_path)


def test_hidden_material_carries_the_canary_and_the_repo_does_not() -> None:
    task = load_task("risk-001")
    marker = canary()
    assert re.fullmatch(r"EVALH-CANARY-[0-9a-f-]{36}", marker)
    for data in read_tree(task.hidden_tests_dir).values():
        assert marker.encode() in data
    assert marker in task.solution_patch.read_text()
    assert marker in (task.path / "task.yaml").read_text()
    assert not any(marker.encode() in data for data in read_tree(task.repo_dir).values())


def test_image_tags_are_content_hashes(tmp_path: Path) -> None:
    task = load_task("risk-001")
    tag = task_image_tag(task)
    assert re.fullmatch(r"evalh-task-risk-001:[0-9a-f]{16}", tag)
    assert re.fullmatch(r"evalh-base-python:[0-9a-f]{16}", base_image_tag("python"))
    assert task_image_tag(task) == tag

    shutil.copytree(task.path, tmp_path / "risk-001")
    copy = load_task("risk-001", bank=tmp_path)
    assert task_image_tag(copy) == tag  # hidden tests and patches are not build inputs
    (copy.path / "solution.patch").write_text("changed")
    assert task_image_tag(copy) == tag
    (copy.repo_dir / "risk" / "formats.py").write_text("# changed\n")
    assert task_image_tag(copy) != tag  # the build context is
