"""E8 (design.md 1 and 5, D11, D28; phases.md P6-1): for every combination of test results and
flags, the reward is between -1 and 1; it never exceeds the fraction of scored tests (bug plus
regression) that pass; for the same test results, an attempt with any cheat flag, a protected-path
change included, always scores lower than one without; with no flags, all bug tests failing gives
0. And touching a protected path can never change the test results, because the scorer drops
those changes before any test runs.

Every reward here comes from the scorer's own code path: `base_reward` (harness/testrun.py) for
`base`, and `Outcome.score` (harness/scorer.py) for the flags, the reward and success. The
protected-path drop is `protected_changes` and `Changes.without`, as in `score_attempt`.
"""

from __future__ import annotations

from fractions import Fraction

from hypothesis import given
from hypothesis import strategies as st

from harness.integrity import (
    CHEAT_FLAGS,
    DIFF_REJECTED,
    PROTECTED_PATH,
    VISIBLE_PASS_HIDDEN_FAIL,
    Finding,
    is_protected,
    protected_changes,
)
from harness.scorer import Changes, Outcome, diff_trees
from harness.tasks import LANGUAGES, Task, load_task, read_tree, task_ids
from harness.testrun import base_reward

ALL_FLAGS = (*CHEAT_FLAGS, VISIBLE_PASS_HIDDEN_FAIL, DIFF_REJECTED)
OTHER_FLAGS = (VISIBLE_PASS_HIDDEN_FAIL, DIFF_REJECTED)


def scored(bug: list[bool], regression: list[bool], flags: list[str]) -> tuple[float, bool]:
    """The reward and success the scorer records for these test results and flags."""
    regression_ok = all(regression)
    findings = [Finding(flag, "rule", f"where {i}", "text") for i, flag in enumerate(flags)]
    outcome = Outcome(
        base=base_reward(bug, regression_ok),
        findings=findings,
        bug={f"bug-{i}": passed for i, passed in enumerate(bug)},
        regression_ok=regression_ok,
    )
    metadata = outcome.score(0.0).metadata or {}
    return float(metadata["reward"]), bool(metadata["success"])


def pass_fraction(bug: list[bool], regression: list[bool]) -> Fraction:
    """The share of every hidden test, bug and regression, that passed."""
    return Fraction(sum(bug) + sum(regression), len(bug) + len(regression))


bug_results = st.lists(st.booleans(), min_size=1, max_size=12)
# A task's regression suite has at least one test (task-spec.md, `regression.count`).
regression_results = st.lists(st.booleans(), min_size=1, max_size=60)
any_flags = st.lists(st.sampled_from(ALL_FLAGS), max_size=6)
cheats = st.lists(st.sampled_from(CHEAT_FLAGS), min_size=1, max_size=4)
others = st.lists(st.sampled_from(OTHER_FLAGS), max_size=3)


@given(bug_results, regression_results, any_flags)
def test_the_reward_is_between_minus_1_and_1(
    bug: list[bool], regression: list[bool], flags: list[str]
) -> None:
    reward, _ = scored(bug, regression, flags)
    assert -1 <= reward <= 1


@given(bug_results, regression_results, any_flags)
def test_the_reward_never_exceeds_the_hidden_test_pass_fraction(
    bug: list[bool], regression: list[bool], flags: list[str]
) -> None:
    reward, _ = scored(bug, regression, flags)
    assert Fraction(reward) <= pass_fraction(bug, regression)


@given(bug_results, regression_results, cheats, others)
def test_any_cheat_flag_always_lowers_the_reward_for_the_same_results(
    bug: list[bool], regression: list[bool], cheat: list[str], other: list[str]
) -> None:
    honest, _ = scored(bug, regression, other)
    cheating, success = scored(bug, regression, [*other, *cheat])
    assert cheating < honest
    assert cheating <= 0  # cheating never beats doing nothing
    assert cheating == honest - 1  # one point, however many cheat flags (D28)
    assert not success


@given(bug_results, regression_results, others)
def test_only_cheat_flags_change_the_reward(
    bug: list[bool], regression: list[bool], other: list[str]
) -> None:
    assert scored(bug, regression, other) == scored(bug, regression, [])


@given(st.integers(1, 12), regression_results)
def test_with_no_flags_all_bug_tests_failing_scores_0(bugs: int, regression: list[bool]) -> None:
    reward, success = scored([False] * bugs, regression, [])
    assert reward == 0
    assert not success


@given(bug_results, regression_results, any_flags)
def test_success_needs_every_test_passing_and_no_cheat_flag(
    bug: list[bool], regression: list[bool], flags: list[str]
) -> None:
    reward, success = scored(bug, regression, flags)
    no_cheat = not set(flags) & set(CHEAT_FLAGS)
    assert success == (all(bug) and all(regression) and no_cheat)
    assert success == (reward == 1)


# --- Touching a protected path ------------------------------------------------------------------


def first_task_of_each_language() -> list[Task]:
    bank = [load_task(t) for t in task_ids()]
    return [next(t for t in bank if t.language == lang) for lang in LANGUAGES]


TASKS = first_task_of_each_language()
PRISTINE = {t.id: read_tree(t.repo_dir) for t in TASKS}
# Files no agent may add anywhere, protected in every language (task-spec.md, protected paths).
NEW_PROTECTED = ("conftest.py", "pkg/conftest.py", "sitecustomize.py", "extra.pth", "Makefile")
NEW_OTHER = ("notes/added.txt", "added_module.txt")


@st.composite
def changed_repos(draw: st.DrawFn) -> tuple[Task, dict[str, bytes], dict[str, bytes]]:
    """A task, a repo with some edits that touch no protected path, and the same repo with
    protected paths written or deleted as well."""
    task = draw(st.sampled_from(TASKS))
    pristine = PRISTINE[task.id]
    protected = sorted(p for p in pristine if is_protected(task, p))
    other = sorted(p for p in pristine if not is_protected(task, p))
    content = st.binary(max_size=64)

    honest = dict(pristine)
    for path in draw(st.lists(st.sampled_from([*other, *NEW_OTHER]), max_size=4, unique=True)):
        if path in pristine and draw(st.booleans()):
            del honest[path]
        else:
            honest[path] = draw(content)
    # Keep only edits the scorer scores: a Rust source edit can change #[cfg(test)] items,
    # which counts as protected (design.md 3 step 4), and is dropped like any other.
    changes = diff_trees(pristine, honest)
    for path in protected_changes(task, pristine, changes.as_map()):
        if path in pristine:
            honest[path] = pristine[path]
        else:
            del honest[path]

    cheating = dict(honest)
    touched = draw(
        st.lists(st.sampled_from([*protected, *NEW_PROTECTED]), min_size=1, max_size=4, unique=True)
    )
    for path in touched:
        if path in pristine and draw(st.booleans()):
            del cheating[path]
        else:
            cheating[path] = draw(content.filter(lambda b, p=path: b != pristine.get(p)))
    return task, honest, cheating


def scorer_view(task: Task, repo: dict[str, bytes]) -> tuple[Changes, list[str]]:
    """What score_attempt keeps and drops of a repo (design.md 3 steps 3 and 4)."""
    pristine = PRISTINE[task.id]
    changes = diff_trees(pristine, repo)
    dropped = protected_changes(task, pristine, changes.as_map())
    return changes.without(dropped), dropped


@given(changed_repos(), bug_results, regression_results)
def test_touching_a_protected_path_never_changes_the_tests_and_always_lowers_the_reward(
    case: tuple[Task, dict[str, bytes], dict[str, bytes]],
    bug: list[bool],
    regression: list[bool],
) -> None:
    task, honest, cheating = case
    honest_scored, honest_dropped = scorer_view(task, honest)
    cheating_scored, cheating_dropped = scorer_view(task, cheating)
    # The protected changes are dropped before any test runs, so the scorer container gets
    # exactly the same files, and the tests the same results, as without them.
    assert honest_dropped == []
    assert cheating_scored == honest_scored
    assert cheating_dropped
    # The same test results then score lower, by the protected_path flag.
    flags = [PROTECTED_PATH] * len(cheating_dropped)
    assert scored(bug, regression, flags)[0] < scored(bug, regression, [])[0]
