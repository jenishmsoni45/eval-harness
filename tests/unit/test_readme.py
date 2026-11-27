"""The README's numbers (phases.md P6-4, R13): every number in README.md sits in the block that
`make report` writes, and the committed block is what a fresh `make report` writes.

"A number" is read as any digit in the README's prose. Outside the block, digits may appear only
where they are not numbers: inside code (fenced blocks and inline spans), in link targets, and in
the identifiers of invariants and decisions (E1 to E8, D71).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from stats import report
from tests.report_logs import Bank, Planned, honest_info, write_eval

FENCED = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")
LINK_TARGET = re.compile(r"\]\([^)\s]*\)")
IDENTIFIER = re.compile(r"\b[ED]\d+\b")


def block_of(text: str) -> str:
    start = text.index(report.README_START)
    end = text.index(report.README_END) + len(report.README_END)
    return text[start:end]


def prose_outside_the_block(text: str) -> str:
    rest = text.replace(block_of(text), "")
    for pattern in (FENCED, INLINE_CODE, LINK_TARGET, IDENTIFIER):
        rest = pattern.sub("", rest)
    return rest


def test_the_readme_block_is_a_fresh_make_report() -> None:
    run = report.read_run(report.LOG_DIR.glob("*.eval"))
    assert block_of(report.README.read_text()) == report.readme_block(run), (
        "run `make report` and commit README.md"
    )


def test_every_number_in_the_readme_sits_in_the_block() -> None:
    rest = prose_outside_the_block(report.README.read_text())
    numbers = [line for line in rest.splitlines() if re.search(r"\d", line)]
    assert not numbers, numbers


def test_the_check_would_catch_a_number_outside_the_block() -> None:
    text = report.README.read_text() + "\nThe strong agent passes 70% of tasks.\n"
    assert re.search(r"\d", prose_outside_the_block(text))
    empty = f"{report.README_START}\n{report.README_END}\n"
    allowed = empty + "See `make e2e`, D71, E8 and [x](a1.md).\n```\nrun 3 times\n```\n"
    assert not re.search(r"\d", prose_outside_the_block(allowed))


def test_writing_the_block_replaces_only_the_block(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(f"before\n{report.README_START}\nold\n{report.README_END}\nafter\n")
    report.write_readme(readme, f"{report.README_START}\nnew\n{report.README_END}")
    assert readme.read_text() == f"before\n{report.README_START}\nnew\n{report.README_END}\nafter\n"


def test_a_readme_without_the_markers_is_refused(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("no markers\n")
    with pytest.raises(ValueError, match="no <!-- report:start -->"):
        report.write_readme(readme, "block")


def test_a_report_of_other_logs_never_touches_the_readme(tmp_path: Path) -> None:
    bank = Bank({"t-easy-py": ("easy", "python"), "t-hard-go": ("hard", "go")})
    plans = {(t, e): Planned(success=e == 1) for t in bank.tasks for e in (1, 2)}
    rates = {"easy": 0.9, "medium": 0.7, "hard": 0.5}
    write_eval(tmp_path, "strong", bank, plans, honest_info("strong", rates, bank))
    before = report.README.read_bytes()
    assert report.main(["--logs", str(tmp_path), "--out", str(tmp_path / "r.md")]) == 0
    assert report.README.read_bytes() == before


def test_an_invalid_run_puts_no_results_in_the_block(tmp_path: Path) -> None:
    bank = Bank({"t-easy-py": ("easy", "python")})
    plans = {("t-easy-py", e): Planned(success=True, infra_failures=3) for e in (1, 2)}
    write_eval(tmp_path, "strong", bank, plans, honest_info("strong", {"easy": 0.9}, bank))
    block = report.readme_block(report.read_run(tmp_path.glob("*.eval")))
    assert "The run is invalid" in block
    assert "pass@1" not in block
    assert "beats" not in block
