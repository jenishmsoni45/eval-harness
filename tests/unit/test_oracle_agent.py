"""The oracle agent applies the reference fix through text_editor and scores base 1 (phases.md
P1-3). Also covers turning a patch into text_editor edits."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from inspect_ai.event import ToolEvent
from inspect_ai.model import ChatMessageAssistant

from harness.agents.oracle import script
from harness.agents.patches import Edit, Hunk, apply_edits, parse_patch, plan_edits
from harness.tasks import load_task

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
        "def f(x):\n    return x < 1\n\n\n", "def f(x):\n    return x <= 1\n\n\n"
    )
    assert files[0].hunks[1] == Hunk(
        "def h(s):\n--- a line that starts like a file header\n    return s\n",
        "def h(s):\n++++ and its replacement\n    return s\n",
    )
    assert files[1].hunks[0] == Hunk("", "X = 1\nY = 2")  # no newline at the end


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


def test_an_ambiguous_hunk_falls_back_to_replacing_the_whole_file(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\ny = 2\nx = 1\n")
    patch = "--- a/a.py\n+++ b/a.py\n@@ -3 +3 @@\n-x = 1\n+x = 3\n"
    assert plan_edits(patch, tmp_path) == [
        Edit("a.py", "x = 1\ny = 2\nx = 1\n", "x = 3\ny = 2\nx = 1\n")
    ]


def test_apply_edits_applies_hunks_in_order() -> None:
    assert apply_edits("a b a b", [Hunk("a", "A"), Hunk("a", "C")]) == "A b C b"


def test_the_oracle_edits_for_risk_001_equal_git_apply(tmp_path: Path) -> None:
    task = load_task("risk-001")
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


@pytest.mark.docker
def test_the_oracle_scores_base_1_on_risk_001(oracle_run: OracleRun) -> None:
    log = oracle_run.log
    assert log.status == "success", log.error
    assert log.eval.model.startswith("mockllm/")
    assert log.samples is not None
    assert len(log.samples) == 1
    sample = log.samples[0]
    assert sample.scores is not None
    [score] = sample.scores.values()
    assert score.value == 1.0
    assert score.metadata is not None
    assert score.metadata["base"] == 1.0
    assert score.metadata["regression_passed"] is True
    assert score.metadata["changed_files"] == ["risk/features/compute.py"]


@pytest.mark.docker
def test_the_oracle_log_shows_bash_and_text_editor_calls(oracle_run: OracleRun) -> None:
    assert oracle_run.log.samples is not None
    sample = oracle_run.log.samples[0]
    tools = [e.function for e in sample.events if isinstance(e, ToolEvent)]
    assert "bash" in tools
    assert "text_editor" in tools
    assert all(e.error is None for e in sample.events if isinstance(e, ToolEvent))
    turns = [m for m in sample.messages if isinstance(m, ChatMessageAssistant)]
    assert all(len(m.tool_calls or []) == 1 for m in turns)  # one tool call per turn (D27)
