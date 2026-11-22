"""The reported problem: with 300 transfers, all scoring differently, the review capacity is 3
but the threshold holds only 2 of them."""

from __future__ import annotations

import numpy as np

from ml.threshold import capacity, held, threshold_for


def test_300_distinct_scores_hold_the_full_capacity_of_3() -> None:
    scores = np.linspace(0.001, 0.3, 300)
    threshold = threshold_for(scores, capacity(scores.size))
    assert capacity(scores.size) == 3
    assert int(held(scores, threshold).sum()) == 3
