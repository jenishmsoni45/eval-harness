"""The minimal scorer's pieces (design.md 3, D11): reading the agent's repo, finding its
changes, reading the regression report, and computing base."""

from __future__ import annotations

import io
import tarfile

import pytest

from harness.scorer import TAR_EXCLUDES, diff_trees, files_from_tar
from harness.tasks import is_ignored, load_task
from harness.testrun import base_reward, count_passed, regression_passed


def tar_of(entries: list[tarfile.TarInfo], data: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for info in entries:
            payload = data.get(info.name, b"")
            info.size = len(payload) if info.isfile() else 0
            tar.addfile(info, io.BytesIO(payload) if info.isfile() else None)
    return buffer.getvalue()


def file_entry(name: str) -> tarfile.TarInfo:
    return tarfile.TarInfo(name)


def link_entry(name: str, target: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.SYMTYPE
    info.linkname = target
    return info


def test_only_regular_non_ignored_files_are_read_from_the_archive() -> None:
    archive = tar_of(
        [
            file_entry("./src/a.py"),
            file_entry("./src/__pycache__/a.cpython-312.pyc"),
            file_entry("./.git/HEAD"),
            file_entry("./b.pyc"),
            link_entry("./leak.py", "/etc/passwd"),
            file_entry("../outside.py"),
        ],
        {
            "./src/a.py": b"A",
            "./src/__pycache__/a.cpython-312.pyc": b"C",
            "./.git/HEAD": b"H",
            "./b.pyc": b"P",
            "../outside.py": b"O",
        },
    )  # fmt: skip
    assert files_from_tar(archive) == {"src/a.py": b"A"}


def test_changes_are_added_modified_and_deleted_files() -> None:
    pristine = {"same.py": b"1", "edited.py": b"old", "gone.py": b"x"}
    current = {"same.py": b"1", "edited.py": b"new", "added.py": b"+"}
    changes = diff_trees(pristine, current)
    assert changes.written == {"added.py": b"+", "edited.py": b"new"}
    assert changes.deleted == ("gone.py",)
    assert changes.paths == ["added.py", "edited.py", "gone.py"]


def test_no_change_means_no_changes() -> None:
    assert diff_trees({"a": b"1"}, {"a": b"1"}).paths == []


def test_the_tar_excludes_cover_every_ignored_path() -> None:
    patterns = {e.removeprefix("--exclude=") for e in TAR_EXCLUDES}
    assert patterns == {".git", "__pycache__", ".pytest_cache", ".hypothesis", "target", "*.pyc"}
    assert all(is_ignored(p) for p in [".git/x", "a/__pycache__/b", "t/target/x", "m.pyc"])
    assert not is_ignored("src/targets.py")


REPORT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest">
<testcase classname="t" name="ok1"/>
<testcase classname="t" name="ok2"><system-out>noise</system-out></testcase>
<testcase classname="t" name="bad"><failure message="x"/></testcase>
<testcase classname="t" name="err"><error message="x"/></testcase>
<testcase classname="t" name="skip"><skipped message="x"/></testcase>
</testsuite></testsuites>"""


def test_only_tests_that_ran_and_passed_are_counted() -> None:
    assert count_passed(load_task("risk-001"), REPORT) == 2


def test_the_regression_run_needs_exit_0_and_the_exact_count() -> None:
    task = load_task("risk-001")
    passing = (
        "<testsuites><testsuite>"
        + '<testcase name="t"/>' * task.regression_count
        + "</testsuite></testsuites>"
    )
    assert regression_passed(task, 0, passing)
    assert not regression_passed(task, 1, passing)
    assert not regression_passed(
        task, 0, passing.replace('<testcase name="t"/>', "", 1)
    )  # one skipped
    assert not regression_passed(task, 0, None)
    assert not regression_passed(task, 0, "not xml")


@pytest.mark.parametrize(
    ("bug", "regression_ok", "base"),
    [
        ([True, True, True], True, 1.0),
        ([True, False, False, False], True, 0.25),
        ([False, False], True, 0.0),
        ([True, True], False, 0.0),
    ],
)
def test_base_is_the_bug_test_share_gated_on_regression(
    bug: list[bool], regression_ok: bool, base: float
) -> None:
    assert base_reward(bug, regression_ok) == base


def test_a_task_without_bug_tests_is_an_error() -> None:
    with pytest.raises(ValueError, match="bug test"):
        base_reward([], True)
