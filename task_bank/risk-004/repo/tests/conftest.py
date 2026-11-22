"""The one Hypothesis profile every run uses (design.md section 11).

The profile is derandomized, so a run generates the same examples everywhere and any failure
replays; Hypothesis prints the failing example. No example database is written.
"""

from __future__ import annotations

from hypothesis import settings

settings.register_profile("repo", derandomize=True, database=None, print_blob=True, deadline=None)
settings.load_profile("repo")
