"""Reading a task from task_bank/<id>/ (task-spec.md).

`load_task` checks task.yaml against the schema of task-spec.md "task.yaml" and raises
`TaskSpecError` naming the offending field. It checks the file only; the task directory's other
contents and every validation rule are checked by scripts/validate_tasks.py.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_BANK = REPO_ROOT / "task_bank"
CANARY_FILE = TASK_BANK / "CANARY"
LANGUAGES = ("python", "go", "rust")
DIFFICULTIES = ("easy", "medium", "hard")

# task-spec.md "Task ids" and "Language specifics": each id prefix names one source project, and
# each project has one language.
PROJECTS = {
    "risk": ("risk-engine", "python"),
    "queue": ("job-queue", "go"),
    "vault": ("vaultline", "rust"),
}
TASK_ID = re.compile(r"(risk|queue|vault)-\d{3}")
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
REPO_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+")
# task-spec.md: bug tests use the runner's own identifiers.
BUG_TEST_ID = {
    "python": re.compile(r"tests/hidden/[\w/.-]+\.py::\S+"),
    "go": re.compile(r"[\w./-]+:Test\w*"),  # <package dir>:<TestName>
    "rust": re.compile(r"hidden_\d+:\w+(::\w+)*"),  # <test target>:<test name>
}

# task-spec.md "Protected paths": never compared and never scored.
IGNORED_DIRS = frozenset({".git", "__pycache__", ".pytest_cache", ".hypothesis", "target"})
IGNORED_SUFFIXES = (".pyc",)

FIELDS = (
    "id",
    "canary",
    "source",
    "language",
    "difficulty",
    "hard_reason",
    "category",
    "visible_tests",
    "hidden_tests",
    "protected_extra",
)
SOURCE_FIELDS = ("project", "repo", "commit", "paths")


class TaskSpecError(ValueError):
    """task.yaml does not match the schema. The message starts with the field's dotted path."""

    def __init__(self, field: str, problem: str) -> None:
        super().__init__(f"{field}: {problem}")
        self.field = field


@dataclass(frozen=True)
class Source:
    project: str
    repo: str
    commit: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class Task:
    id: str
    canary: str
    source: Source
    language: str
    difficulty: str
    hard_reason: str | None
    category: str
    visible_command: tuple[str, ...]
    bug_tests: tuple[str, ...]
    regression_command: tuple[str, ...]
    regression_count: int
    protected_extra: tuple[str, ...]
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
    def wrong_patch(self) -> Path:
        return self.path / "wrong.patch"

    @property
    def partial_patch(self) -> Path:
        return self.path / "partial.patch"

    @property
    def patches(self) -> dict[str, Path]:
        return {
            "solution.patch": self.solution_patch,
            "wrong.patch": self.wrong_patch,
            "partial.patch": self.partial_patch,
        }

    @property
    def instructions(self) -> str:
        return (self.path / "instructions.md").read_text()


def _mapping(value: Any, field: str, keys: tuple[str, ...]) -> dict[str, Any]:
    """A mapping with exactly these keys: every field is required, and an unknown one is a typo.
    `field` is the mapping's dotted path, or "task.yaml" for the whole file."""
    if not isinstance(value, dict):
        raise TaskSpecError(field, f"must be a mapping, got {type(value).__name__}")
    prefix = "" if field == "task.yaml" else f"{field}."
    for key in keys:
        if key not in value:
            raise TaskSpecError(f"{prefix}{key}", "is required")
    for key in value:
        if key not in keys:
            raise TaskSpecError(f"{prefix}{key}", "is not a task.yaml field")
    return value


def _string(value: Any, field: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaskSpecError(field, "must be a non-empty string")
    if pattern is not None and not pattern.fullmatch(value):
        raise TaskSpecError(field, f"{value!r} does not match {pattern.pattern}")
    return value


def _choice(value: Any, field: str, choices: tuple[str, ...]) -> str:
    if value not in choices:
        raise TaskSpecError(field, f"must be one of {', '.join(choices)}, got {value!r}")
    return str(value)


def _strings(value: Any, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if value is None and allow_empty:
        return ()
    if not isinstance(value, list) or (not value and not allow_empty):
        raise TaskSpecError(field, "must be a non-empty list of strings")
    for i, item in enumerate(value):
        _string(item, f"{field}[{i}]")
    return tuple(value)


def _relative_paths(value: Any, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    paths = _strings(value, field, allow_empty=allow_empty)
    for i, path in enumerate(paths):
        if path.startswith("/") or ".." in path.split("/"):
            raise TaskSpecError(f"{field}[{i}]", f"{path!r} must be a path inside the repo")
    return paths


def parse_task(raw: Any, task_id: str, path: Path) -> Task:
    """Check a parsed task.yaml against the schema and return the task."""
    raw = _mapping(raw, "task.yaml", FIELDS)
    found_id = _string(raw["id"], "id", TASK_ID)
    if found_id != task_id:
        raise TaskSpecError("id", f"{found_id!r} does not match the directory name {task_id!r}")
    project, language_of_project = PROJECTS[found_id.split("-")[0]]

    source = _mapping(raw["source"], "source", SOURCE_FIELDS)
    if source["project"] != project:
        raise TaskSpecError(
            "source.project", f"a {found_id.split('-')[0]}-* task comes from {project}"
        )
    language = _choice(raw["language"], "language", LANGUAGES)
    if language != language_of_project:
        raise TaskSpecError("language", f"{project} tasks are {language_of_project}")

    difficulty = _choice(raw["difficulty"], "difficulty", DIFFICULTIES)
    hard_reason = raw["hard_reason"]
    if hard_reason is not None:
        hard_reason = _string(hard_reason, "hard_reason")

    visible = _mapping(raw["visible_tests"], "visible_tests", ("command",))
    hidden = _mapping(raw["hidden_tests"], "hidden_tests", ("bug_tests", "regression"))
    regression = _mapping(hidden["regression"], "hidden_tests.regression", ("command", "count"))
    count = regression["count"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise TaskSpecError("hidden_tests.regression.count", "must be a non-negative integer")
    bug_tests = _strings(hidden["bug_tests"], "hidden_tests.bug_tests")
    for i, test in enumerate(bug_tests):
        _string(test, f"hidden_tests.bug_tests[{i}]", BUG_TEST_ID[language])
    if len(set(bug_tests)) != len(bug_tests):
        raise TaskSpecError("hidden_tests.bug_tests", "lists a test twice")

    return Task(
        id=found_id,
        canary=_string(raw["canary"], "canary"),
        source=Source(
            project=project,
            repo=_string(source["repo"], "source.repo", REPO_URL),
            commit=_string(source["commit"], "source.commit", COMMIT_SHA),
            paths=_relative_paths(source["paths"], "source.paths"),
        ),
        language=language,
        difficulty=difficulty,
        hard_reason=hard_reason,
        category=_string(raw["category"], "category"),
        visible_command=_strings(visible["command"], "visible_tests.command"),
        bug_tests=bug_tests,
        regression_command=_strings(regression["command"], "hidden_tests.regression.command"),
        regression_count=count,
        protected_extra=_relative_paths(
            raw["protected_extra"], "protected_extra", allow_empty=True
        ),
        path=path,
    )


def load_task(task_id: str, bank: Path = TASK_BANK) -> Task:
    path = bank / task_id
    try:
        raw = yaml.safe_load((path / "task.yaml").read_text())
    except yaml.YAMLError as error:
        raise TaskSpecError("task.yaml", f"is not valid YAML: {error}") from error
    return parse_task(raw, task_id, path)


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


def patched_files(task: Task, patch: Path) -> dict[str, bytes | None]:
    """The files a patch changes in the task's snapshot, with their content after `git apply` on
    the host (None if deleted). Raises CalledProcessError if the patch does not apply."""
    with tempfile.TemporaryDirectory(prefix="evalh-patch-") as tmp:
        work = Path(tmp) / "repo"
        shutil.copytree(task.repo_dir, work)
        subprocess.run(
            ["git", "apply", str(patch.resolve())], cwd=work, check=True, capture_output=True
        )
        before, after = read_tree(task.repo_dir), read_tree(work)
    changed: dict[str, bytes | None] = {p: d for p, d in after.items() if before.get(p) != d}
    changed |= {p: None for p in before if p not in after}
    return changed


@cache
def reference_changes(task: Task) -> dict[str, bytes | None]:
    """What the reference fix changes (D66), computed once per task."""
    return patched_files(task, task.solution_patch)
