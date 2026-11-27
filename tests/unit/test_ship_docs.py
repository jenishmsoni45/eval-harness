"""The postmortem and the talk outline (phases.md P6-5): they exist, have every part they need,
point only at files that exist, and state no number (R13): the talk takes its numbers from the
README's block, which `make report` writes."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from harness.tasks import REPO_ROOT

POSTMORTEM = REPO_ROOT / "docs" / "postmortem.md"
TALK = REPO_ROOT / "docs" / "talk-outline.md"
POSTMORTEM_SECTIONS = (
    "Summary",
    "Impact",
    "How it was found",
    "Root cause",
    "The fix (D71)",
    "Verification",
    "What remains",
    "Lessons",
)
# PLAN.md section 6: the talk covers the tasks, sandbox, grading, statistics, demo and RL parts.
TALK_TOPICS = ("tasks", "sandbox", "reward hacking", "statistics", "demo", "rl environments")
NOT_NUMBERS = re.compile(
    r"`[^`\n]*`|\]\([^)\s]*\)|\b[EDR]\d+\b|§\d+|\bPhase \d\b|\bpass@\d+|^#+ \d+\.", re.MULTILINE
)


def headings(text: str) -> list[str]:
    return [line.lstrip("#").strip() for line in text.splitlines() if line.startswith("## ")]


def test_the_postmortem_has_every_part() -> None:
    assert headings(POSTMORTEM.read_text()) == list(POSTMORTEM_SECTIONS)


def test_the_talk_outline_covers_every_topic_and_the_questions() -> None:
    text = TALK.read_text()
    titles = [h.casefold() for h in headings(text)]
    for topic in TALK_TOPICS:
        assert any(topic in t for t in titles), topic
    assert titles[-1] == "questions to be ready for"


@pytest.mark.parametrize("path", [POSTMORTEM, TALK], ids=lambda p: p.name)
def test_every_file_it_names_exists(path: Path) -> None:
    text = path.read_text()
    named = re.findall(r"`((?:harness|rl|stats|scripts|tests|docs)/[\w./-]+)`", text)
    missing = [p for p in named if not (REPO_ROOT / p).exists()]
    assert not missing, missing


@pytest.mark.parametrize("path", [POSTMORTEM, TALK], ids=lambda p: p.name)
def test_it_states_no_number(path: Path) -> None:
    text = path.read_text()
    lines = [line for line in NOT_NUMBERS.sub("", text).splitlines() if re.search(r"\d", line)]
    assert not lines, lines


def test_neither_has_placeholders() -> None:
    for path in (POSTMORTEM, TALK):
        assert not re.search(r"\b(TODO|TBD|FIXME|XXX)\b", path.read_text()), path.name
