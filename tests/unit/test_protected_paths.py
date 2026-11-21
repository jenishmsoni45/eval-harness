"""Protected paths (task-spec.md "Protected paths", D9), as V10 uses them: matching by name per
language, `protected_extra`, and Rust's `#[cfg(test)]` items. Phase 4 adds the scorer's use."""

from __future__ import annotations

import dataclasses

import pytest

from harness.integrity import (
    cfg_test_items,
    cfg_test_module_files,
    code_only,
    glob_regex,
    is_protected,
    protected_changes,
)
from harness.tasks import Task, load_task

PY, GO, RUST = (load_task(t) for t in ("risk-001", "queue-001", "vault-001"))


@pytest.mark.parametrize(
    ("pattern", "path", "matches"),
    [
        ("tests/**", "tests/a.py", True),
        ("tests/**", "tests/hidden/b/c.py", True),
        ("tests/**", "src/tests.py", False),
        ("**/conftest.py", "conftest.py", True),
        ("**/conftest.py", "risk/x/conftest.py", True),
        ("**/conftest.py", "risk/conftest.py.bak", False),
        ("**/*_test.go", "internal/scheduler/zz_hidden_1_test.go", True),
        ("**/*_test.go", "internal/scheduler/drr.go", False),
        ("**/.cargo/**", ".cargo/config.toml", True),
        ("**/*.pth", "lib/evil.pth", True),
        ("risk/?.py", "risk/a.py", True),
        ("risk/?.py", "risk/ab.py", False),
    ],
)
def test_globs_match_whole_segments(pattern: str, path: str, matches: bool) -> None:
    assert bool(glob_regex(pattern).fullmatch(path)) is matches


@pytest.mark.parametrize(
    ("task", "path", "protected"),
    [
        (PY, "tests/visible/test_windows.py", True),
        (PY, "tests/hidden/test_window_edges.py", True),
        (PY, "pyproject.toml", True),
        (PY, "risk/conftest.py", True),  # wherever it is added
        (PY, "risk/sitecustomize.py", True),
        (PY, "Makefile", True),
        (PY, "risk/features/compute.py", False),
        (PY, "requirements.txt", False),
        (PY, ".git/config", False),  # ignored, not protected
        (GO, "internal/scheduler/scheduler_test.go", True),
        (GO, "go.mod", True),
        (GO, "go.sum", True),
        (GO, "internal/scheduler/drr.go", False),
        (RUST, "tests/invariants/s7_masking.rs", True),
        (RUST, "Cargo.toml", True),
        (RUST, "Cargo.lock", True),
        (RUST, "build.rs", True),
        (RUST, ".cargo/config.toml", True),
        (RUST, "src/inject/mask.rs", False),  # protected by content only
    ],
)
def test_each_language_protects_its_defaults(task: Task, path: str, protected: bool) -> None:
    assert is_protected(task, path) is protected


def test_protected_extra_adds_task_specific_paths() -> None:
    task = dataclasses.replace(PY, protected_extra=("risk/formats.py", "data/**"))
    assert is_protected(task, "risk/formats.py")
    assert is_protected(task, "data/x/y.csv")
    assert not is_protected(PY, "risk/formats.py")


RUST_SOURCE = """\
pub fn masked(s: &str) -> String {
    let brace = '{';            // a char literal with a brace
    let text = "}}} #[cfg(test)] {";  /* a comment { */
    let raw = r#"mod tests { "#;
    format!("{s}{brace}{text}{raw}")
}

fn lifetimes<'a>(x: &'a str) -> &'a str { x }

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    #[test]
    fn a() {
        let close = '}';
        assert_eq!(masked("x").len(), 30 + close.len_utf8());
    }
}

#[cfg(test)]
const SIZES: [usize; 2] = [1, 2];

#[cfg(test)]
mod more;
"""


def test_cfg_test_items_are_found_whole_despite_braces_in_literals_and_comments() -> None:
    items = cfg_test_items(RUST_SOURCE)
    assert len(items) == 3
    assert items[0].startswith("#[cfg(test)]\n#[allow(clippy::unwrap_used)]\nmod tests {")
    assert items[0].endswith("    }\n}")
    assert items[1] == "#[cfg(test)]\nconst SIZES: [usize; 2] = [1, 2];"
    assert items[2] == "#[cfg(test)]\nmod more;"


def test_code_only_blanks_comments_and_literals_but_keeps_offsets() -> None:
    code = code_only(RUST_SOURCE)
    assert len(code) == len(RUST_SOURCE)
    assert code.count("\n") == RUST_SOURCE.count("\n")
    assert "#[cfg(test)] {" not in code  # the one inside a string literal
    assert "fn lifetimes<'a>(x: &'a str)" in code  # lifetimes are not literals


def test_a_test_only_file_is_one_item() -> None:
    source = "#![cfg(test)]\nfn helper() {}\n"
    assert cfg_test_items(source) == [source]


def test_a_cfg_test_module_declaration_names_its_files() -> None:
    assert cfg_test_module_files("src/vault/mod.rs", "#[cfg(test)]\nmod tests;\n") == [
        "src/vault/tests.rs",
        "src/vault/tests/mod.rs",
    ]
    assert cfg_test_module_files("src/audit.rs", "#[cfg(test)]\npub(crate) mod tests;\n") == [
        "src/audit/tests.rs",
        "src/audit/tests/mod.rs",
    ]
    assert cfg_test_module_files("src/lib.rs", "mod tests;\n") == []


def test_a_rust_change_is_protected_only_inside_cfg_test_items() -> None:
    pristine = {
        "src/a.rs": RUST_SOURCE.encode(),
        "src/b.rs": b"#[cfg(test)]\nmod more;\n",
    }
    outside = RUST_SOURCE.replace("{s}{brace}", "{brace}{s}")
    inside = RUST_SOURCE.replace("30 + close", "31 + close")
    new_test = RUST_SOURCE + "\n#[cfg(test)]\nfn extra() {}\n"
    assert protected_changes(RUST, pristine, {"src/a.rs": outside.encode()}) == []
    assert protected_changes(RUST, pristine, {"src/a.rs": inside.encode()}) == ["src/a.rs"]
    assert protected_changes(RUST, pristine, {"src/a.rs": new_test.encode()}) == ["src/a.rs"]
    assert protected_changes(RUST, pristine, {"src/b/more.rs": b"fn x() {}"}) == ["src/b/more.rs"]
    assert protected_changes(RUST, pristine, {"tests/x.rs": None}) == ["tests/x.rs"]


def test_the_masker_files_test_module_is_protected_and_its_code_is_not() -> None:
    path = "src/inject/mask.rs"
    source = (RUST.repo_dir / path).read_text()
    pristine = {path: source.encode()}
    code_change = source.replace("start < h && end > h", "start <= h && end > h")
    test_change = source.replace("fn the_marker_is_the_documented_text", "fn renamed")
    assert code_change != source
    assert test_change != source
    assert protected_changes(RUST, pristine, {path: code_change.encode()}) == []
    assert protected_changes(RUST, pristine, {path: test_change.encode()}) == [path]
