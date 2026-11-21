"""Reading a task from task_bank/<id>/ (task-spec.md).

Phase 1 reads only the fields the harness uses and checks their types; the full schema and its
error messages arrive with the task loader in Phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_BANK = REPO_ROOT / "task_bank"
CANARY_FILE = TASK_BANK / "CANARY"
LANGUAGES = ("python", "go", "rust")

# task-spec.md "Protected paths": never compared and never scored.
IGNORED_DIRS = frozenset({".git", "__pycache__", ".pytest_cache", ".hypothesis", "target"})
IGNORED_SUFFIXES = (".pyc",)


@dataclass(frozen=True)
class Task:
    id: str
    language: str
    difficulty: str
    visible_command: tuple[str, ...]
    bug_tests: tuple[str, ...]
    regression_command: tuple[str, ...]
    regression_count: int
    path: Path

    @property
    def repo_dir(self) -> Path:
        return self.path / "repo"

    @property
    def dockerfile(self) -> Path:
        return self.path / "Dockerfile"

    @property
    def hidden_tests_dir(self) -> Path:
        return self.path / "hidden_tests"

    @property
    def solution_patch(self) -> Path:
        return self.path / "solution.patch"

    @property
    def instructions(self) -> str:
        return (self.path / "instructions.md").read_text()


def _str_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{field} must be a non-empty list of strings")
    return tuple(value)


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return value


def load_task(task_id: str, bank: Path = TASK_BANK) -> Task:
    path = bank / task_id
    raw = _mapping(yaml.safe_load((path / "task.yaml").read_text()), "task.yaml")
    if raw.get("id") != task_id:
        raise ValueError(f"task.yaml id {raw.get('id')!r} does not match directory {task_id!r}")
    language = raw.get("language")
    if language not in LANGUAGES:
        raise ValueError(f"language must be one of {LANGUAGES}, got {language!r}")
    difficulty = raw.get("difficulty")
    if not isinstance(difficulty, str):
        raise ValueError("difficulty must be a string")
    visible = _mapping(raw.get("visible_tests"), "visible_tests")
    hidden = _mapping(raw.get("hidden_tests"), "hidden_tests")
    regression = _mapping(hidden.get("regression"), "hidden_tests.regression")
    count = regression.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ValueError("hidden_tests.regression.count must be a non-negative integer")
    return Task(
        id=task_id,
        language=language,
        difficulty=difficulty,
        visible_command=_str_list(visible.get("command"), "visible_tests.command"),
        bug_tests=_str_list(hidden.get("bug_tests"), "hidden_tests.bug_tests"),
        regression_command=_str_list(regression.get("command"), "hidden_tests.regression.command"),
        regression_count=count,
        path=path,
    )


def task_ids(bank: Path = TASK_BANK) -> list[str]:
    """Every task directory in the bank, sorted."""
    return sorted(p.name for p in bank.iterdir() if (p / "task.yaml").is_file())


def is_ignored(relpath: str) -> bool:
    """Whether a path inside a repo is ignored entirely (task-spec.md)."""
    parts = relpath.split("/")
    return any(part in IGNORED_DIRS for part in parts) or relpath.endswith(IGNORED_SUFFIXES)


def read_tree(root: Path) -> dict[str, bytes]:
    """Every regular, non-ignored file under root, keyed by its path relative to root."""
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and not path.is_symlink() and not is_ignored(rel):
            files[rel] = path.read_bytes()
    return files


def canary() -> str:
    return CANARY_FILE.read_text().strip()
