"""Rule evaluation (design.md section 5, D21). Phase 4, criterion 2: the strictest fired action
wins, every fired rule is listed in file order, and no fired rule gives `default`. Table-driven.
"""

from __future__ import annotations

import dataclasses

import pytest

from risk.features.compute import FEATURE_NAMES
from risk.rules.ruleset import Condition, Rule, RuleSet

ZERO = dict.fromkeys(FEATURE_NAMES, 0)


def rule_set(*rules: Rule) -> RuleSet:
    return RuleSet(version=1, default="allow", on_timeout="hold", sha256="0" * 64, rules=rules)


def features(**values: int) -> dict[str, int]:
    return ZERO | {"amount": 1} | values


HOLD_AMOUNT = Rule("hold_amount", "hold", (Condition("amount", ">=", 100),))
HOLD_VELOCITY = Rule("hold_velocity", "hold", (Condition("out_count_1m", ">=", 5),))
BLOCK_ATTEMPTS = Rule("block_attempts", "block", (Condition("attempt_count_1m", ">=", 10),))
# Fires only when both conditions hold.
BLOCK_PASS = Rule(
    "block_pass", "block", (Condition("in_sum_1h", ">=", 1000), Condition("amount", ">=", 500))
)
ALL = (HOLD_AMOUNT, HOLD_VELOCITY, BLOCK_ATTEMPTS, BLOCK_PASS)

# name: (the rules in file order, the features, the expected decision and fired list)
CASES: dict[str, tuple[tuple[Rule, ...], dict[str, int], str, list[str]]] = {
    "no rules: default": ((), features(amount=10**9), "allow", []),
    "rules, none fired: default": (ALL, features(), "allow", []),
    "one hold fires": (ALL, features(amount=100), "hold", ["hold_amount"]),
    "one block fires": (ALL, features(attempt_count_1m=10), "block", ["block_attempts"]),
    "two holds fire, both listed in file order": (
        ALL,
        features(amount=100, out_count_1m=5),
        "hold",
        ["hold_amount", "hold_velocity"],
    ),
    "a rule with one condition short doesn't fire": (
        ALL,
        features(in_sum_1h=1000, amount=499),
        "hold",
        ["hold_amount"],
    ),
}


@pytest.mark.parametrize(("rules", "values", "decision", "fired"), CASES.values(), ids=CASES.keys())
def test_evaluation(
    rules: tuple[Rule, ...], values: dict[str, int], decision: str, fired: list[str]
) -> None:
    assert rule_set(*rules).evaluate(values) == (decision, fired)


# op: whether it holds for a feature of 9, 10 and 11 against a value of 10.
OPERATORS: dict[str, tuple[bool, bool, bool]] = {
    ">": (False, False, True),
    ">=": (False, True, True),
    "<": (True, False, False),
    "<=": (True, True, False),
    "==": (False, True, False),
    "!=": (True, False, True),
}


@pytest.mark.parametrize(("op", "expected"), OPERATORS.items(), ids=OPERATORS.keys())
def test_each_operator_compares_the_feature_with_the_value(
    op: str, expected: tuple[bool, bool, bool]
) -> None:
    rules = rule_set(Rule("r", "hold", (Condition("out_sum_24h", op, 10),)))
    for value, fires in zip((9, 10, 11), expected, strict=True):
        assert rules.evaluate(features(out_sum_24h=value)) == (
            ("hold", ["r"]) if fires else ("allow", [])
        ), (op, value)


def test_the_rule_set_is_immutable() -> None:
    """design.md section 5: the loaded rule set doesn't change for the life of the process."""
    rules = rule_set(*ALL)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rules.rules = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        ALL[0].conditions[0].value = 1  # type: ignore[misc]
    assert isinstance(rules.rules, tuple)
    assert isinstance(ALL[3].conditions, tuple)

