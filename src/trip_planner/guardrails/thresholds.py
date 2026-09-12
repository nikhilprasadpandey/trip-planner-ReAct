"""Deterministic policy-threshold evaluation, read from config/guardrails.yaml
(spec §3.4: "Guardrail policy lives in a config file, not hardcoded logic").

This is the source of truth for "is this fare in policy" — the Policy
Agent's LLM explanation must agree with this, never override it. If they
disagree, trust this module and treat the LLM's claim as ungrounded
(see guardrails/groundedness.py).
"""
from __future__ import annotations

from typing import TypedDict

from trip_planner.config_loader import job_level_policy


class ThresholdEvaluation(TypedDict):
    within_policy: bool
    requires_approval: bool
    cap_usd: float
    approver_role: str
    cabin_class_allowed: bool
    max_cabin_class: str


_CABIN_TIERS = ["economy", "premium_economy", "business", "first"]


def _cabin_rank(cabin_class: str) -> int:
    try:
        return _CABIN_TIERS.index(cabin_class)
    except ValueError:
        return len(_CABIN_TIERS)  # unknown cabin class treated as "above everything" -> not allowed


def evaluate_fare(
    job_level: str,
    price_usd: float,
    cabin_class: str,
    is_international: bool = False,
) -> ThresholdEvaluation:
    policy = job_level_policy(job_level)
    if policy is None:
        raise ValueError(f"No guardrail policy configured for job_level={job_level!r}")

    cap_usd = policy["international_spend_cap_usd"] if is_international else policy["domestic_spend_cap_usd"]
    cabin_allowed = _cabin_rank(cabin_class) <= _cabin_rank(policy["max_cabin_class"])
    within_price = price_usd <= cap_usd
    within_policy = within_price and cabin_allowed

    return ThresholdEvaluation(
        within_policy=within_policy,
        requires_approval=not within_policy,
        cap_usd=float(cap_usd),
        approver_role=policy["approver_role"],
        cabin_class_allowed=cabin_allowed,
        max_cabin_class=policy["max_cabin_class"],
    )


def next_lower_cabin_class(cabin_class: str) -> str | None:
    """Used by the orchestrator's reflection loop (spec §3.1) — the Policy
    Agent asks the Flight Agent for a lower-cabin alternative before giving
    up and routing to approval. Returns None if already at the lowest tier."""
    rank = _cabin_rank(cabin_class)
    if rank <= 0:
        return None
    return _CABIN_TIERS[rank - 1]
