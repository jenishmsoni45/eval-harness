"""The oracle agent applies the reference fix through text_editor and scores base 1 (phases.md
P1-3). Also covers turning a patch into text_editor edits."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from inspect_ai.event import ModelEvent, ToolEvent
from inspect_ai.log import EvalSample
from inspect_ai.tool import ToolDef, bash, text_editor

from harness.agents.oracle import script
from harness.agents.patches import Edit, Hunk, apply_hunks, parse_patch, plan_edits
from harness.tasks import load_task, task_ids
from scripts.validate_tasks import patch_stats

if TYPE_CHECKING:
    from tests.conftest import OracleRun

PATCH = """\
# a header comment, as patches carry the canary
diff --git a/pkg/mod.py b/pkg/mod.py
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -1,4 +1,4 @@
 def f(x):
-    return x < 1
+    return x <= 1


@@ -8,3 +8,3 @@ def g():
 def h(s):
---- a line that starts like a file header
+++++ and its replacement
     return s
diff --git a/pkg/new.py b/pkg/new.py
new file mode 100644
--- /dev/null
+++ b/pkg/new.py
@@ -0,0 +1,2 @@
+X = 1
+Y = 2
\\ No newline at end of file
"""


def test_a_patch_is_parsed_into_files_and_hunks() -> None:
    files = parse_patch(PATCH)
    assert [(f.path, f.new_file, len(f.hunks)) for f in files] == [
        ("pkg/mod.py", False, 2),
        ("pkg/new.py", True, 1),
    ]
    assert files[0].hunks[0] == Hunk(
        "def f(x):\n    return x < 1\n\n\n", "def f(x):\n    return x <= 1\n\n\n", 1
    )
    assert files[0].hunks[1] == Hunk(
        "def h(s):\n--- a line that starts like a file header\n    return s\n",
        "def h(s):\n++++ and its replacement\n    return s\n",
        8,
    )
    assert files[1].hunks[0] == Hunk("", "X = 1\nY = 2", 0)  # no newline at the end


def test_edits_are_one_replace_per_hunk_and_a_create_per_new_file(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    original = (
        "def f(x):\n    return x < 1\n\n\ndef g():\n    pass\n\n"
        "def h(s):\n--- a line that starts like a file header\n    return s\n"
    )
    (tmp_path / "pkg" / "mod.py").write_text(original)
    edits = plan_edits(PATCH, tmp_path)
    assert [(e.path, e.old is None) for e in edits] == [("pkg/mod.py", False)] * 2 + [
        ("pkg/new.py", True)
    ]
    content = original
    for edit in edits[:2]:
        assert edit.old is not None
        assert content.count(edit.old) == 1
        content = content.replace(edit.old, edit.new, 1)
    assert "return x <= 1" in content
    assert "++++ and its replacement" in content


def test_an_ambiguous_hunk_is_applied_at_its_own_line(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\ny = 2\nx = 1\n")
    patch = "--- a/a.py\n+++ b/a.py\n@@ -3 +3 @@\n-x = 1\n+x = 3\n"
    expected = Edit("a.py", "x = 1\ny = 2\nx = 1\n", "x = 1\ny = 2\nx = 3\n")
    assert plan_edits(patch, tmp_path) == [expected]


def test_apply_hunks_uses_line_numbers_and_checks_each_hunk() -> None:
    content = "a\nb\na\nb\n"
    assert apply_hunks(content, [Hunk("a\n", "A\n", 1), Hunk("a\n", "C\n", 3)]) == "A\nb\nC\nb\n"
    assert apply_hunks(content, [Hunk("", "new\n", 2)]) == "a\nb\nnew\na\nb\n"
    with pytest.raises(ValueError, match="does not match"):
        apply_hunks(content, [Hunk("b\n", "B\n", 1)])


@pytest.mark.parametrize("task_id", task_ids())
def test_the_oracle_edits_equal_git_apply(task_id: str, tmp_path: Path) -> None:
    task = load_task(task_id)
    patch = task.solution_patch.read_text()
    shutil.copytree(task.repo_dir, tmp_path / "repo")
    subprocess.run(["git", "apply", str(task.solution_patch)], cwd=tmp_path / "repo", check=True)
    for fp in parse_patch(patch):
        content = (task.repo_dir / fp.path).read_text()
        for edit in (e for e in plan_edits(patch, task.repo_dir) if e.path == fp.path):
            assert edit.old is not None
            assert content.count(edit.old) == 1
            content = content.replace(edit.old, edit.new, 1)
        assert content == (tmp_path / "repo" / fp.path).read_text()


def test_the_oracle_follows_the_scripted_trajectory() -> None:
    steps = script("risk-001")
    assert all(len(s.message.tool_calls or []) == 1 for s in steps)
    calls = [call for s in steps for call in s.message.tool_calls or []]
    assert [c.function for c in calls] == ["bash", "text_editor", "text_editor", "bash", "submit"]
    editor = [c.arguments["command"] for c in calls if c.function == "text_editor"]
    assert editor == ["view", "str_replace"]


@pytest.mark.parametrize("task_id", task_ids())
def test_every_scripted_call_matches_the_real_tools_parameters(task_id: str) -> None:
    schemas = {
        name: ToolDef(tool).parameters
        for name, tool in [("bash", bash()), ("text_editor", text_editor())]
    }
    for call in (c for s in script(task_id) for c in s.message.tool_calls or []):
        if call.function == "submit":
            assert set(call.arguments) == {"answer"}
            continue
        params = schemas[call.function]
        assert set(call.arguments) <= set(params.properties), call
        assert set(params.required) <= set(call.arguments), call


def samples_by_task(run: OracleRun) -> dict[str, EvalSample]:
    assert run.log.samples is not None
    return {str(sample.id): sample for sample in run.log.samples}


@pytest.mark.docker
def test_the_oracle_scores_base_1_on_every_task(oracle_run: OracleRun) -> None:
    """phases.md P1-3 and P2-6: one attempt per task, each with base 1, logged as mockllm."""
    log = oracle_run.log
    assert log.status == "success", log.error
    assert log.eval.model.startswith("mockllm/")
    samples = samples_by_task(oracle_run)
    assert sorted(samples) == task_ids()
    for task_id, sample in samples.items():
        assert sample.scores is not None
        [score] = sample.scores.values()
        assert score.value == 1.0, (task_id, score.explanation)
        assert score.metadata is not None
        assert score.metadata["base"] == 1.0
        assert score.metadata["regression_passed"] is True
        assert all(score.metadata["bug_tests"].values())
        fixed = list(patch_stats(load_task(task_id).solution_patch).files)
        assert score.metadata["changed_files"] == fixed


@pytest.mark.docker
def test_the_oracle_log_shows_bash_and_text_editor_calls(oracle_run: OracleRun) -> None:
    for sample in samples_by_task(oracle_run).values():
        tools = [e.function for e in sample.events if isinstance(e, ToolEvent)]
        assert "bash" in tools
        assert "text_editor" in tools
        assert all(e.error is None for e in sample.events if isinstance(e, ToolEvent))
        # One tool call per turn (D27): every model output asks for exactly one.
        outputs = [e.output for e in sample.events if isinstance(e, ModelEvent)]
        assert [len(o.message.tool_calls or []) for o in outputs] == [1] * len(tools)


# What each runner prints when every test it ran passed, and what it prints for a failure. The
# visible tests of medium and hard tasks pass on the shipped bug; an easy task's reproduction test
# fails, and it is the only test that does.
ALL_PASSED = {
    "python": r"\b\d+ passed\b",
    "go": r"(?m)^ok\s+\S+",
    "rust": r"test result: ok\. \d+ passed",
}
FAILURE = {"python": "failed", "go": "FAIL", "rust": "FAILED"}
ONE_FAILED = {
    "python": r"\b1 failed, \d+ passed\b",
    "go": r"(?m)^--- FAIL: ",
    "rust": r"test result: FAILED\. \d+ passed; 1 failed",
}


@pytest.mark.docker
def test_the_visible_tests_run_in_the_agents_shell(oracle_run: OracleRun) -> None:
    """The preamble's test command works in the agent's (login) shell, offline, for every
    language: on an easy task exactly one test, the reproduction test, fails before the fix, and
    on every task every visible test passes after it."""
    for task_id, sample in samples_by_task(oracle_run).items():
        runs = [
            str(e.result)
            for e in sample.events
            if isinstance(e, ToolEvent) and e.function == "bash"
        ]
        assert len(runs) == 2, task_id
        before, after = runs
        task = load_task(task_id)
        assert re.search(ALL_PASSED[task.language], after), (task_id, after)
        assert FAILURE[task.language] not in after, (task_id, after)
        if task.difficulty == "easy":
            assert len(re.findall(ONE_FAILED[task.language], before)) == 1, (task_id, before)
        else:
            assert re.search(ALL_PASSED[task.language], before), (task_id, before)
            assert FAILURE[task.language] not in before, (task_id, before)
