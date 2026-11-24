"""Which tests the file-changing cheaters work on when a Rust task has no test file (D69)."""

from __future__ import annotations

from harness.agents.cheaters import (
    FileChange,
    deleted_test,
    edited_test,
    skipped_tests,
    target_test_file,
)
from harness.integrity import cfg_test_items, protected_changes
from harness.tasks import load_task, read_tree

UNIT_TESTS_ONLY = "vault-003"


def _as_changed(changes: list[FileChange]) -> dict[str, bytes | None]:
    return {c.path: None if c.new is None else c.new.encode() for c in changes}


def test_a_task_with_only_unit_tests_targets_a_source_file_with_tests() -> None:
    task = load_task(UNIT_TESTS_ONLY)
    path = target_test_file(task)
    assert path.startswith("src/")
    assert cfg_test_items((task.repo_dir / path).read_text())


def test_every_trick_on_unit_tests_is_a_protected_change() -> None:
    task = load_task(UNIT_TESTS_ONLY)
    pristine = read_tree(task.repo_dir)
    for trick in (edited_test, deleted_test, skipped_tests):
        changed = _as_changed(trick(task))
        assert protected_changes(task, pristine, changed) == sorted(changed), trick.__name__


def test_delete_test_removes_the_test_modules_and_keeps_the_code() -> None:
    task = load_task(UNIT_TESTS_ONLY)
    [change] = deleted_test(task)
    assert change.new is not None
    original = (task.repo_dir / change.path).read_text()
    expected = original
    for item in cfg_test_items(original):
        expected = expected.replace(item, "", 1)
    assert change.new == expected
    assert cfg_test_items(change.new) == []
