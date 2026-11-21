"""The reported problem: a payment made exactly one hour before a decision is missing from the
decision's one-hour features."""

from __future__ import annotations

from risk.features.compute import HOUR_MS, DecisionMembers, Member, features_at

T = 1_800_000_000_000


def test_a_payment_exactly_one_hour_old_counts_in_the_1h_features() -> None:
    members = DecisionMembers(
        sender_out=[Member(T - HOUR_MS, 2500)],
        sender_in=[],
        sender_attempts=[],
        receiver_in=[],
        receiver_out=[],
    )
    features = features_at(T, 100, members)
    assert features["out_count_1h"] == 1
    assert features["out_sum_1h"] == 2500
