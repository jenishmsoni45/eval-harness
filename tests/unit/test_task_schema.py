"""The task.yaml schema (task-spec.md "task.yaml"; phases.md P2-1): every task in the bank loads,
and the loader rejects each malformed case with a message that names the field."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from harness.tasks import FIELDS, TASK_BANK, TaskSpecError, load_task, parse_task, task_ids

Raw = dict[str, Any]


def raw_task(task_id: str = "risk-001") -> Raw:
    data: Raw = yaml.safe_load((TASK_BANK / task_id / "task.yaml").read_text())
    return data


def rejected(raw: Any, task_id: str = "risk-001") -> TaskSpecError:
    with pytest.raises(TaskSpecError) as caught:
        parse_task(raw, task_id, TASK_BANK / task_id)
    return caught.value


def test_every_task_in_the_bank_loads() -> None:
    assert task_ids() == ["queue-001", "risk-001", "vault-001"]
    for task_id in task_ids():
        task = load_task(task_id)
        assert task.id == task_id
        assert len(task.source.commit) == 40  # P2-7: the full SHA is recorded


@pytest.mark.parametrize("field", FIELDS)
def test_every_top_level_field_is_required(field: str) -> None:
    raw = raw_task()
    del raw[field]
    error = rejected(raw)
    assert (error.field, str(error)) == (field, f"{field}: is required")


@pytest.mark.parametrize("field", ["project", "repo", "commit", "paths"])
def test_every_source_field_is_required(field: str) -> None:
    raw = raw_task()
    del raw["source"][field]
    assert rejected(raw).field == f"source.{field}"


def test_a_misspelt_field_is_named() -> None:
    raw = raw_task()
    raw["difficulity"] = raw.pop("difficulty")
    assert rejected(raw).field == "difficulty"  # missing first
    raw["difficulty"] = "easy"
    assert rejected(raw).field == "difficulity"


def setter(path: str, value: Any) -> Callable[[Raw], None]:
    """A mutation that sets the field at a dotted path."""

    def mutate(raw: Raw) -> None:
        *parents, last = path.split(".")
        target = raw
        for key in parents:
            target = target[key]
        target[last] = value

    return mutate


# (description, mutation, the field the message must name)
CASES: list[tuple[str, Callable[[Raw], None], str]] = [
    ("id is not <project>-<NNN>", setter("id", "risk-1"), "id"),
    ("id names another project", setter("id", "ledger-007"), "id"),
    ("canary is empty", setter("canary", ""), "canary"),
    ("canary is not a string", setter("canary", 7), "canary"),
    ("source is not a mapping", setter("source", "risk-engine"), "source"),
    ("source.project is another project", setter("source.project", "vaultline"), "source.project"),
    ("source.repo is not a GitHub URL", setter("source.repo", "git@github.com:x/y"), "source.repo"),
    ("source.commit is short", setter("source.commit", "0b00ff8"), "source.commit"),
    ("source.commit is upper case", setter("source.commit", "A" * 40), "source.commit"),
    ("source.paths is empty", setter("source.paths", []), "source.paths"),
    ("source.paths is a string", setter("source.paths", "risk/"), "source.paths"),
    ("a source path is absolute", setter("source.paths", ["/etc/passwd"]), "source.paths[0]"),
    ("a source path leaves the repo", setter("source.paths", ["a", "../b"]), "source.paths[1]"),
    ("a source path is not a string", setter("source.paths", [3]), "source.paths[0]"),
    ("language is unknown", setter("language", "java"), "language"),
    ("language is not the project's", setter("language", "go"), "language"),
    ("difficulty is unknown", setter("difficulty", "trivial"), "difficulty"),
    ("hard_reason is empty", setter("hard_reason", ""), "hard_reason"),
    ("hard_reason is not text", setter("hard_reason", 3), "hard_reason"),
    ("category is empty", setter("category", "  "), "category"),
    ("visible_tests is a list", setter("visible_tests", ["pytest"]), "visible_tests"),
    ("visible_tests has no command", setter("visible_tests", {}), "visible_tests.command"),
    ("the visible command is empty", setter("visible_tests.command", []), "visible_tests.command"),
    (
        "the visible command is one string",
        setter("visible_tests.command", "pytest tests/visible"),
        "visible_tests.command",
    ),
    (
        "a visible command argument is a number",
        setter("visible_tests.command", ["pytest", 3]),
        "visible_tests.command[1]",
    ),
    (
        "hidden_tests has no bug tests",
        setter("hidden_tests.bug_tests", []),
        "hidden_tests.bug_tests",
    ),
    (
        "a bug test is not a pytest node id under tests/hidden",
        setter("hidden_tests.bug_tests", ["test_window_edge"]),
        "hidden_tests.bug_tests[0]",
    ),
    (
        "a bug test is listed twice",
        setter("hidden_tests.bug_tests", ["tests/hidden/a.py::t", "tests/hidden/a.py::t"]),
        "hidden_tests.bug_tests",
    ),
    (
        "regression has no count",
        setter("hidden_tests.regression", {"command": ["pytest"]}),
        "hidden_tests.regression.count",
    ),
    (
        "regression has an unknown field",
        setter("hidden_tests.regression.timeout", 60),
        "hidden_tests.regression.timeout",
    ),
    (
        "the regression count is negative",
        setter("hidden_tests.regression.count", -1),
        "hidden_tests.regression.count",
    ),
    (
        "the regression count is a boolean",
        setter("hidden_tests.regression.count", True),
        "hidden_tests.regression.count",
    ),
    (
        "the regression count is text",
        setter("hidden_tests.regression.count", "50"),
        "hidden_tests.regression.count",
    ),
    (
        "the regression command is empty",
        setter("hidden_tests.regression.command", []),
        "hidden_tests.regression.command",
    ),
    ("protected_extra is a string", setter("protected_extra", "tests/"), "protected_extra"),
    ("a protected_extra path is absolute", setter("protected_extra", ["/x"]), "protected_extra[0]"),
]


@pytest.mark.parametrize(("mutate", "field"), [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_a_malformed_field_is_rejected_and_named(mutate: Callable[[Raw], None], field: str) -> None:
    raw = copy.deepcopy(raw_task())
    mutate(raw)
    error = rejected(raw)
    assert error.field == field
    assert str(error).startswith(f"{field}: ")


def test_the_id_must_match_the_directory() -> None:
    error = rejected(raw_task(), task_id="risk-002")
    assert error.field == "id"
    assert "does not match the directory name" in str(error)


@pytest.mark.parametrize(
    ("task_id", "bad_id"),
    [
        ("queue-001", "TestDRRUpdateKeepsAnOpenTurn"),  # Go needs <package>:<TestName>
        ("queue-001", "internal/scheduler:testLowerCase"),
        ("vault-001", "tests/hidden_1.rs:coverage"),  # Rust needs <target>:<test name>
        ("vault-001", "invariants:coverage"),  # a hidden target is hidden_<n>
    ],
)
def test_bug_test_ids_follow_each_runners_format(task_id: str, bad_id: str) -> None:
    raw = raw_task(task_id)
    raw["hidden_tests"]["bug_tests"] = [bad_id]
    assert rejected(raw, task_id).field == "hidden_tests.bug_tests[0]"


def test_hard_reason_and_protected_extra_may_be_empty() -> None:
    raw = raw_task()
    raw["protected_extra"] = None
    assert parse_task(raw, "risk-001", TASK_BANK / "risk-001").protected_extra == ()


@pytest.mark.parametrize("text", ["- just\n- a list\n", "id: [unclosed\n"])
def test_a_file_that_is_not_a_task_mapping_is_rejected(text: str, tmp_path: Path) -> None:
    (tmp_path / "risk-001").mkdir()
    (tmp_path / "risk-001" / "task.yaml").write_text(text)
    with pytest.raises(TaskSpecError) as caught:
        load_task("risk-001", bank=tmp_path)
    assert caught.value.field == "task.yaml"
