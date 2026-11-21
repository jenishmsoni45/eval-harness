"""One test per validation rule (task-spec.md "Validation rules"; phases.md P2-2): each breaks a
copy of a real task in one way and checks that the rule rejects it.

The host rules (V1, V4's build context, V9's fix size, V10, V12) need no Docker. The others build
the broken copy's image and validate it with one run per state; risk-001, the Python task, is
the fastest to run, and an appended Dockerfile line reuses the cached layers before it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from harness.tasks import TASK_BANK, load_task
from scripts.validate_tasks import check_host, validate


def copy_task(tmp_path: Path, task_id: str = "risk-001") -> Path:
    shutil.copytree(TASK_BANK / task_id, tmp_path / task_id)
    return tmp_path / task_id


def host_problems(bank: Path, task_id: str = "risk-001") -> list[str]:
    return check_host(task_id, bank)[1].problems()


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, f"{old!r} not in {path}"
    path.write_text(text.replace(old, new, 1))


def rules(problems: list[str]) -> set[str]:
    return {p.split(":", 1)[0] for p in problems}


# --- Host rules ----------------------------------------------------------------------------


def test_v1_rejects_a_schema_error(tmp_path: Path) -> None:
    task = copy_task(tmp_path)
    edit(task / "task.yaml", "difficulty: easy", "difficulty: trivial")
    [problem] = host_problems(tmp_path)
    assert problem.startswith("V1: task.yaml: difficulty: must be one of")


def test_v1_rejects_a_canary_that_differs_from_the_bank(tmp_path: Path) -> None:
    task = copy_task(tmp_path)
    edit(task / "task.yaml", 'canary: "EVALH-CANARY-', 'canary: "EVALH-CANARY-0')
    assert host_problems(tmp_path) == ["V1: canary does not match task_bank/CANARY"]


def test_v1_rejects_a_task_without_its_wrong_patch(tmp_path: Path) -> None:
    task = copy_task(tmp_path)
    (task / "wrong.patch").unlink()
    assert host_problems(tmp_path) == ["V1: missing wrong.patch"]


def test_v4_rejects_hidden_material_in_the_build_context(tmp_path: Path) -> None:
    task = copy_task(tmp_path)
    canary = load_task("risk-001").canary
    with (task / "repo" / "risk" / "formats.py").open("a") as f:
        f.write(f"# {canary}\n")
    shutil.copy(task / "solution.patch", task / "repo" / "notes.txt")
    problems = host_problems(tmp_path)
    assert f"V4: repo/risk/formats.py contains {canary!r}" in problems
    assert "V4: repo/notes.txt is a copy of hidden material" in problems
    assert rules(problems) == {"V4"}


def test_v9_rejects_a_hard_label_on_a_one_file_fix_without_a_reason(tmp_path: Path) -> None:
    task = copy_task(tmp_path)
    edit(task / "task.yaml", "difficulty: easy", "difficulty: hard")
    assert host_problems(tmp_path) == ["V9: a hard fix in one file needs a hard_reason"]


def test_v9_rejects_an_easy_label_on_a_fix_over_five_lines(tmp_path: Path) -> None:
    task = copy_task(tmp_path, "queue-001")
    edit(task / "task.yaml", "difficulty: medium", "difficulty: easy")
    shutil.copy(task / "partial.patch", task / "solution.patch")  # 5 added, 1 removed
    assert host_problems(tmp_path, "queue-001") == [
        "V9: easy allows a fix of 1 file and at most 5 changed lines; "
        "solution.patch changes 1 file(s) and 6 lines"
    ]


def test_v10_rejects_a_patch_that_touches_a_test(tmp_path: Path) -> None:
    task = copy_task(tmp_path)
    first = (task / "repo" / "tests" / "visible" / "test_windows.py").read_text().splitlines()[0]
    with (task / "wrong.patch").open("a") as f:
        f.write(
            "diff --git a/tests/visible/test_windows.py b/tests/visible/test_windows.py\n"
            "--- a/tests/visible/test_windows.py\n"
            "+++ b/tests/visible/test_windows.py\n"
            f"@@ -1,1 +1,2 @@\n+# changed\n {first}\n"
        )
    assert host_problems(tmp_path) == [
        "V10: wrong.patch touches the protected path tests/visible/test_windows.py"
    ]


def test_v10_rejects_a_hidden_test_outside_the_protected_paths(tmp_path: Path) -> None:
    task = copy_task(tmp_path)
    hidden = task / "hidden_tests" / "tests" / "hidden" / "test_window_edges.py"
    (task / "hidden_tests" / "risk").mkdir()
    shutil.copy(hidden, task / "hidden_tests" / "risk" / "test_extra.py")
    assert host_problems(tmp_path) == [
        "V10: hidden test risk/test_extra.py is not inside a protected path"
    ]


def test_v10_rejects_a_rust_patch_that_changes_a_cfg_test_module(tmp_path: Path) -> None:
    task = copy_task(tmp_path, "vault-001")
    mask = (task / "repo" / "src" / "inject" / "mask.rs").read_text().splitlines()
    i = mask.index("    fn the_marker_is_the_documented_text() {")
    with (task / "partial.patch").open("a") as f:  # a second hunk, inside the test module
        f.write(
            f"@@ -{i},3 +{i},3 @@\n {mask[i - 1]}\n-{mask[i]}\n+{mask[i]} // x\n {mask[i + 1]}\n"
        )
    assert host_problems(tmp_path, "vault-001") == [
        "V10: partial.patch touches the protected path src/inject/mask.rs"
    ]


def test_v12_rejects_a_hidden_test_without_the_canary(tmp_path: Path) -> None:
    task = copy_task(tmp_path)
    hidden = task / "hidden_tests" / "tests" / "hidden" / "regression" / "test_window_interior.py"
    lines = hidden.read_text().splitlines(keepends=True)
    hidden.write_text("".join(line for line in lines if "EVALH-CANARY" not in line))
    assert host_problems(tmp_path) == [
        "V12: hidden_tests/tests/hidden/regression/test_window_interior.py lacks the canary string"
    ]


# --- Rules that need the image and runs ------------------------------------------------------


def docker_problems(bank: Path, task_id: str = "risk-001", **kwargs: float) -> list[str]:
    return validate(task_id, bank=bank, runs=1, **kwargs)


def append_to_dockerfile(task: Path, lines: str) -> None:
    with (task / "Dockerfile").open("a") as f:
        f.write(lines)


@pytest.mark.docker
def test_v2_rejects_an_image_that_does_not_build(docker_engine: None, tmp_path: Path) -> None:
    append_to_dockerfile(copy_task(tmp_path), "RUN false\n")
    [problem] = docker_problems(tmp_path)
    assert problem.startswith("V2: docker build of evalh-task-risk-001:")


@pytest.mark.docker
def test_v2_rejects_visible_tests_that_do_not_run(docker_engine: None, tmp_path: Path) -> None:
    task = copy_task(tmp_path)
    edit(task / "task.yaml", "tests/visible]", "tests/nowhere]")
    problems = docker_problems(tmp_path)
    assert "V2: the visible tests did not run on the shipped bug (no test passed)" in problems


@pytest.mark.docker
def test_v3_rejects_source_history_in_the_image(docker_engine: None, tmp_path: Path) -> None:
    """phases.md P2-4: a second commit, or another .git directory, is source history."""
    append_to_dockerfile(
        copy_task(tmp_path),
        "RUN GIT_AUTHOR_NAME=evalh GIT_AUTHOR_EMAIL=evalh@localhost GIT_COMMITTER_NAME=evalh "
        "GIT_COMMITTER_EMAIL=evalh@localhost git commit --quiet --allow-empty --message more "
        "&& mkdir -p /home/agent/old-checkout/.git\n",
    )
    problems = [p for p in docker_problems(tmp_path) if p.startswith("V3")]
    assert problems == [
        "V3: /work/repo/.git holds 2 commits, not exactly 1",
        "V3: other .git directories: ['/home/agent/old-checkout/.git']",
    ]


@pytest.mark.docker
def test_v3_rejects_a_commit_whose_tree_is_not_the_snapshot(
    docker_engine: None, tmp_path: Path
) -> None:
    task = copy_task(tmp_path)
    edit(
        task / "Dockerfile",
        "git add --all",
        "git add --all && git rm --quiet --cached pyproject.toml",
    )
    problems = [p for p in docker_problems(tmp_path) if p.startswith("V3")]
    assert problems == [
        "V3: the commit's tree differs from the snapshot: extra [], missing ['pyproject.toml']"
    ]


@pytest.mark.docker
def test_v4_rejects_hidden_material_in_the_image_and_its_history(
    docker_engine: None, tmp_path: Path
) -> None:
    """phases.md P2-5: the build context is clean, but a layer writes the canary into a file."""
    canary = load_task("risk-001").canary
    append_to_dockerfile(copy_task(tmp_path), f"RUN echo {canary} > /home/agent/notes\n")
    problems = [p for p in docker_problems(tmp_path) if p.startswith("V4")]
    assert problems == [
        "V4: /home/agent/notes in the image contains hidden material",
        f"V4: docker history contains {canary!r}",
    ]


@pytest.mark.docker
def test_v5_rejects_a_shipped_bug_that_does_not_fail_a_bug_test(
    docker_engine: None, tmp_path: Path
) -> None:
    task = copy_task(tmp_path)
    edit(
        task / "repo" / "risk" / "features" / "compute.py",
        "return t_ms - width_ms < time_ms < t_ms",
        "return t_ms - width_ms <= time_ms < t_ms",
    )
    problems = docker_problems(tmp_path)
    assert any(p.startswith("V5: shipped bug, run 1: bug test passed") for p in problems)


@pytest.mark.docker
def test_v6_rejects_a_fix_that_does_not_fix(docker_engine: None, tmp_path: Path) -> None:
    task = copy_task(tmp_path)
    edit(
        task / "solution.patch",
        "+    return t_ms - width_ms <= time_ms < t_ms\n",
        "+    return t_ms - width_ms < time_ms < t_ms  # unchanged\n",
    )
    problems = docker_problems(tmp_path)
    assert any(p.startswith("V6: reference fix, run 1: bug test failed") for p in problems)


@pytest.mark.docker
def test_v7_rejects_a_wrong_patch_that_passes_every_bug_test(
    docker_engine: None, tmp_path: Path
) -> None:
    task = copy_task(tmp_path)
    shutil.copy(task / "solution.patch", task / "wrong.patch")
    problems = docker_problems(tmp_path)
    assert problems == ["V7: wrong patch, run 1: every bug test passed with the wrong patch"]


@pytest.mark.docker
def test_v8_rejects_a_partial_patch_that_passes_every_bug_test(
    docker_engine: None, tmp_path: Path
) -> None:
    task = copy_task(tmp_path)
    shutil.copy(task / "solution.patch", task / "partial.patch")
    problems = docker_problems(tmp_path)
    assert problems == [
        "V8: partial patch, run 1: 3 of 3 bug tests passed with the partial patch; "
        "it must pass some but not all"
    ]


@pytest.mark.docker
def test_v9_rejects_a_medium_label_when_a_visible_test_fails_on_the_bug(
    docker_engine: None, tmp_path: Path
) -> None:
    task = copy_task(tmp_path)
    edit(task / "task.yaml", "difficulty: easy", "difficulty: medium")
    problems = docker_problems(tmp_path)
    assert rules(problems) == {"V9"}
    assert problems[0].startswith(
        "V9: a medium task's visible tests must all pass on the shipped bug:"
    )


@pytest.mark.docker
def test_v13_rejects_a_task_whose_scoring_tests_take_too_long(
    docker_engine: None, tmp_path: Path
) -> None:
    copy_task(tmp_path)
    problems = docker_problems(tmp_path, scoring_limit_s=0.2)
    assert len(problems) == 1
    assert problems[0].startswith("V13: the scoring tests took ")
    assert problems[0].endswith("with the reference fix, over half the 0.2 s scoring limit")
