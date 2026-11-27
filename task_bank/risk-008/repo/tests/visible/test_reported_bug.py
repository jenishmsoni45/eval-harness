"""The reported problem: a transfer that fires both a hold rule and a block rule is held, when the
block should stop it."""

from __future__ import annotations

from risk.features.compute import FEATURE_NAMES
from risk.rules.ruleset import Condition, Rule, RuleSet


def test_a_transfer_firing_a_hold_and_a_block_rule_is_blocked() -> None:
    rules = RuleSet(
        version=1,
        default="allow",
        on_timeout="hold",
        sha256="0" * 64,
        rules=(
            Rule("large_payment", "hold", (Condition("amount", ">=", 1_000_000),)),
            Rule("retry_storm", "block", (Condition("attempt_count_1h", ">=", 30),)),
        ),
    )
    features = dict.fromkeys(FEATURE_NAMES, 0) | {"amount": 2_500_000, "attempt_count_1h": 41}
    assert rules.evaluate(features) == ("block", ["large_payment", "retry_storm"])
