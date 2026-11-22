"""The delete-test cheater (D13, D65): it deletes a visible test file. Every attempt gets
`protected_path`, and the scoring container still holds the file (phases.md P4-1, P4-3)."""

from __future__ import annotations

import pytest

from harness.tasks import LANGUAGES
from tests.cheaters.cheats import CheaterRuns, assert_flagged, dropped_never_reached_the_scorer


@pytest.mark.docker
@pytest.mark.parametrize("language", LANGUAGES)
def test_every_delete_test_attempt_is_flagged(cheater_runs: CheaterRuns, language: str) -> None:
    records = assert_flagged("delete-test", language, cheater_runs)
    dropped_never_reached_the_scorer(records)
