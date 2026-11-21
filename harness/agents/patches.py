"""Turning a task's patch into text_editor edits (D14, design.md 6).

Scripted agents read a patch on the host (a test fixture standing in for a model's skill) and
change the sandbox's repo only through their normal tools. Each changed file becomes one
`str_replace` per hunk, replacing the hunk's old lines (context and removed) with its new lines
(context and added). If a hunk's old text is not unique in the file, the file is patched by the
hunks' line numbers instead and replaced in one edit. A new file becomes one `create`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

NO_NEWLINE = "\\ No newline at end of file"


@dataclass(frozen=True)
class Hunk:
    old: str
    new: str
    old_start: int = 0  # the hunk header's first old line (for an empty old side, the line before)


@dataclass
class FilePatch:
    path: str  # relative to the repo root
    new_file: bool = False
    deleted: bool = False
    hunks: list[Hunk] = field(default_factory=list)


@dataclass(frozen=True)
class Edit:
    """One text_editor call: `str_replace` (old -> new) or, when old is None, `create`."""

    path: str
    old: str | None
    new: str


def _strip_prefix(name: str) -> str:
    return name.split("\t")[0].removeprefix("a/").removeprefix("b/")


def parse_patch(text: str) -> list[FilePatch]:
    """Parse a unified diff (as `git diff` writes it) into files and hunks."""
    files: list[FilePatch] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            old_name, new_name = line[4:], lines[i + 1][4:]
            current = FilePatch(
                path=_strip_prefix(new_name if new_name != "/dev/null" else old_name),
                new_file=old_name == "/dev/null",
                deleted=new_name == "/dev/null",
            )
            files.append(current)
            i += 2
            continue
        if line.startswith("@@") and files:
            i = _parse_hunk(lines, i, files[-1])
            continue
        i += 1
    return files


HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,(\d+))? @@")


def _parse_hunk(lines: list[str], i: int, target: FilePatch) -> int:
    """Read the hunk whose header is lines[i], using the header's line counts, so a removed
    line that itself starts with "--" cannot be mistaken for a file header."""
    header = HUNK_HEADER.match(lines[i])
    if header is None:
        raise ValueError(f"malformed hunk header: {lines[i]!r}")
    old_start = int(header.group(1))
    old_left = int(header.group(2) or "1")
    new_left = int(header.group(3) or "1")
    old: list[str] = []
    new: list[str] = []
    last_sides = ""
    i += 1
    while i < len(lines) and (old_left > 0 or new_left > 0 or lines[i] == NO_NEWLINE):
        line = lines[i]
        if line == NO_NEWLINE:
            for side in last_sides:
                buf = old if side == "o" else new
                buf[-1] = buf[-1].removesuffix("\n")
        elif line.startswith("-"):
            old.append(line[1:] + "\n")
            old_left -= 1
            last_sides = "o"
        elif line.startswith("+"):
            new.append(line[1:] + "\n")
            new_left -= 1
            last_sides = "n"
        else:  # context; some tools strip the leading space of an empty context line
            old.append(line[1:] + "\n")
            new.append(line[1:] + "\n")
            old_left -= 1
            new_left -= 1
            last_sides = "on"
        i += 1
    target.hunks.append(Hunk("".join(old), "".join(new), old_start))
    return i


def plan_edits(patch_text: str, repo: Path) -> list[Edit]:
    """The text_editor edits that turn the pristine repo into the patched one."""
    edits: list[Edit] = []
    for fp in parse_patch(patch_text):
        if fp.deleted:
            raise NotImplementedError(f"{fp.path}: deleting a file needs bash, not text_editor")
        if fp.new_file:
            edits.append(Edit(fp.path, None, "".join(h.new for h in fp.hunks)))
            continue
        content = (repo / fp.path).read_text()
        file_edits: list[Edit] = []
        for hunk in fp.hunks:
            if content.count(hunk.old) != 1:
                break
            file_edits.append(Edit(fp.path, hunk.old, hunk.new))
            content = content.replace(hunk.old, hunk.new, 1)
        else:
            edits += file_edits
            continue
        # A hunk's old text is ambiguous: patch by line numbers and replace the whole file.
        original = (repo / fp.path).read_text()
        edits.append(Edit(fp.path, original, apply_hunks(original, fp.hunks)))
    return edits


def apply_hunks(content: str, hunks: list[Hunk]) -> str:
    """Apply hunks at the old-side lines their headers name, checking each one matches."""
    lines = content.splitlines(keepends=True)
    for hunk in sorted(hunks, key=lambda h: h.old_start, reverse=True):
        old_lines = hunk.old.splitlines(keepends=True)
        start = hunk.old_start - 1 if old_lines else hunk.old_start
        if "".join(lines[start : start + len(old_lines)]) != hunk.old:
            raise ValueError(f"hunk at old line {hunk.old_start} does not match the file")
        lines[start : start + len(old_lines)] = hunk.new.splitlines(keepends=True)
    return "".join(lines)
