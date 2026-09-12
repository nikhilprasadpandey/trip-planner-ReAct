"""Deterministic policy-threshold checks (spec §3.4, §8: two job levels,
same fare, different — correctly scoped — outcome)."""
from __future__ import annotations

import pytest

from trip_planner.guardrails.thresholds import evaluate_fare, next_lower_cabin_class


def test_ic_domestic_fare_within_cap_is_in_policy():
    result = evaluate_fare(job_level="ic", price_usd=550, cabin_class="economy")
    assert result["within_policy"] is True
    assert result["cap_usd"] == 600


def test_same_fare_out_of_policy_for_ic_but_in_policy_for_manager():
    """The acceptance-criteria demo moment: identical fare, different
    (correctly scoped) outcome by job level — never leaking one tier's
    threshold as another's."""
    fare_price = 900.0

    ic_result = evaluate_fare(job_level="ic", price_usd=fare_price, cabin_class="economy")
    manager_result = evaluate_fare(job_level="manager", price_usd=fare_price, cabin_class="economy")

    assert ic_result["within_policy"] is False
    assert ic_result["cap_usd"] == 600
    assert manager_result["within_policy"] is True
    assert manager_result["cap_usd"] == 1200


def test_cabin_class_above_eligibility_is_out_of_policy_even_under_cap():
    result = evaluate_fare(job_level="ic", price_usd=500, cabin_class="business")
    assert result["cabin_class_allowed"] is False
    assert result["within_policy"] is False


def test_international_cap_used_when_flagged():
    result = evaluate_fare(job_level="ic", price_usd=1500, cabin_class="economy", is_international=True)
    assert result["within_policy"] is True  # under the $1800 international cap
    assert result["cap_usd"] == 1800


def test_unknown_job_level_raises():
    with pytest.raises(ValueError):
        evaluate_fare(job_level="intern", price_usd=100, cabin_class="economy")


@pytest.mark.parametrize(
    "cabin,expected",
    [("first", "business"), ("business", "premium_economy"), ("premium_economy", "economy"), ("economy", None)],
)
def test_next_lower_cabin_class(cabin, expected):
    assert next_lower_cabin_class(cabin) == expected
