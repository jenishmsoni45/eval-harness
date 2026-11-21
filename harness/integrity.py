"""Integrity checks (architecture.md, design.md 4). Phase 2 has the protected paths that the
validator's V10 needs; Phase 4 adds the scorer's use and the runner-detection and snooping checks.

Protected paths (task-spec.md "Protected paths", D9): a change to one is dropped before scoring
and flagged. Paths are relative to the repo root. Configuration files are matched at any depth,
which protects a nested copy as well (a stricter reading of the spec's list, D47).

Rust also protects every `#[cfg(test)]` item in `src/`: a source file whose `#[cfg(test)]` items
changed, or a module file that a `#[cfg(test)] mod name;` declares, counts as a protected change.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import cache

from harness.tasks import Task, is_ignored

COMMON = (
    "**/conftest.py",
    "**/sitecustomize.py",
    "**/usercustomize.py",
    "**/*.pth",
    "**/Makefile",
)
DEFAULTS = {
    "python": (
        "tests/**",
        "**/pyproject.toml",
        "**/pytest.ini",
        "**/setup.cfg",
        "**/tox.ini",
        "**/uv.lock",
    ),
    "go": ("**/*_test.go", "**/go.mod", "**/go.sum"),
    "rust": ("tests/**", "**/Cargo.toml", "**/Cargo.lock", "**/build.rs", "**/.cargo/**"),
}


@cache
def glob_regex(pattern: str) -> re.Pattern[str]:
    """A glob over `/`-separated paths: `**` is any number of whole segments, `*` and `?` stay
    inside one segment."""
    parts = pattern.split("/")
    out = ""
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if part == "**":
            out += ".+" if last else "(?:[^/]+/)*"
            continue
        out += "".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in part)
        if not last:
            out += "/"
    return re.compile(out)


def patterns(task: Task) -> tuple[str, ...]:
    return (*COMMON, *DEFAULTS[task.language], *task.protected_extra)


def is_protected(task: Task, relpath: str) -> bool:
    """Whether a path is protected by name. `.git/` and the cache paths are ignored, not
    protected; Rust's `#[cfg(test)]` items are checked by content (`protected_changes`)."""
    if is_ignored(relpath):
        return False
    return any(glob_regex(p).fullmatch(relpath) for p in patterns(task))


# --- Rust: #[cfg(test)] items -------------------------------------------------------------

CFG_TEST = re.compile(r"#\s*\[\s*cfg\s*\(\s*test\s*\)\s*\]")
CFG_TEST_INNER = re.compile(r"#!\s*\[\s*cfg\s*\(\s*test\s*\)\s*\]")
MOD_DECLARATION = re.compile(r"(?:pub(?:\s*\([^)]*\))?\s+)?mod\s+(\w+)\s*;\s*$")
RAW_STRING = re.compile(r'(?:br|cr|r)(#*)"')


def code_only(source: str) -> str:
    """`source` with every comment and string or character literal replaced by spaces (newlines
    kept), so brackets and attributes can be found by offset."""
    out = list(source)
    i, n = 0, len(source)

    def blank(start: int, end: int) -> None:
        for k in range(start, min(end, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = source[i]
        if source.startswith("//", i):
            end = source.find("\n", i)
            end = n if end < 0 else end
            blank(i, end)
            i = end
        elif source.startswith("/*", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if source.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif source.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            blank(i, j)
            i = j
        elif (m := RAW_STRING.match(source, i)) and (i == 0 or not _ident(source[i - 1])):
            close = '"' + m.group(1)
            end = source.find(close, m.end())
            end = n if end < 0 else end + len(close)
            blank(i, end)
            i = end
        elif c == '"' or (
            c in "bc" and source.startswith('"', i + 1) and not _prev_ident(source, i)
        ):
            j = i + (1 if c == '"' else 2)
            while j < n and source[j] != '"':
                j += 2 if source[j] == "\\" else 1
            blank(i, j + 1)
            i = j + 1
        elif c == "'":
            literal_end = _char_literal_end(source, i)
            if literal_end is None:
                i += 1  # a lifetime or a label
            else:
                blank(i, literal_end)
                i = literal_end
        else:
            i += 1
    return "".join(out)


def _ident(c: str) -> bool:
    return c.isalnum() or c == "_"


def _prev_ident(source: str, i: int) -> bool:
    return i > 0 and _ident(source[i - 1])


def _char_literal_end(source: str, i: int) -> int | None:
    """The end of the character literal that starts at source[i] == "'", or None for a
    lifetime."""
    if source.startswith("\\", i + 1):
        j = i + 2
        while j < len(source) and source[j] != "'":
            j += 2 if source[j] == "\\" else 1
        return j + 1
    if i + 2 < len(source) and source[i + 2] == "'":
        return i + 3
    return None


def _item_end(code: str, start: int) -> int:
    """The end of the item that starts at `start` in `code` (after its attributes): its closing
    brace, or a semicolon outside every bracket."""
    depth = 0
    i = start
    while i < len(code):
        c = code[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if c == "}" and depth == 0:
                return i + 1
        elif c == ";" and depth == 0:
            return i + 1
        i += 1
    return len(code)


def _skip_attributes(code: str, i: int) -> int:
    """Skip whitespace and outer attributes `#[...]` starting at i."""
    while True:
        while i < len(code) and code[i].isspace():
            i += 1
        if not code.startswith("#[", i) and not re.match(r"#\s+\[", code[i:]):
            return i
        i = code.index("[", i)
        depth = 0
        while i < len(code):
            if code[i] == "[":
                depth += 1
            elif code[i] == "]":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1


def cfg_test_items(source: str) -> list[str]:
    """The source text of every item marked `#[cfg(test)]`, attribute included; the whole file
    if it starts with `#![cfg(test)]`."""
    code = code_only(source)
    if CFG_TEST_INNER.search(code):
        return [source]
    items = []
    for match in CFG_TEST.finditer(code):
        body = _skip_attributes(code, match.end())
        items.append(source[match.start() : _item_end(code, body)])
    return items


def cfg_test_module_files(relpath: str, source: str) -> list[str]:
    """Paths of the module files that `#[cfg(test)] mod name;` declarations in this file name."""
    code = code_only(source)
    directory = relpath.rsplit("/", 1)[0] if "/" in relpath else ""
    stem = relpath.rsplit("/", 1)[-1].removesuffix(".rs")
    if stem not in ("mod", "lib", "main"):
        directory = f"{directory}/{stem}" if directory else stem
    files = []
    for match in CFG_TEST.finditer(code):
        body = _skip_attributes(code, match.end())
        item = code[body : _item_end(code, body)]
        declared = MOD_DECLARATION.match(item.strip())
        if declared:
            name = declared.group(1)
            files += [f"{directory}/{name}.rs", f"{directory}/{name}/mod.rs"]
    return files


def protected_changes(
    task: Task,
    pristine: Mapping[str, bytes],
    changed: Mapping[str, bytes | None],
) -> list[str]:
    """The changed paths (new content, or None for a deleted file) that touch something
    protected, given the pristine repo's files."""
    rust_test_files: set[str] = set()
    if task.language == "rust":
        for path, data in pristine.items():
            if path.startswith("src/") and path.endswith(".rs"):
                rust_test_files.update(cfg_test_module_files(path, data.decode(errors="replace")))
    touched = []
    for path, new in sorted(changed.items()):
        if is_protected(task, path) or path in rust_test_files:
            touched.append(path)
        elif task.language == "rust" and path.startswith("src/") and path.endswith(".rs"):
            old = pristine.get(path, b"").decode(errors="replace")
            new_text = (new or b"").decode(errors="replace")
            if cfg_test_items(old) != cfg_test_items(new_text):
                touched.append(path)
    return touched
