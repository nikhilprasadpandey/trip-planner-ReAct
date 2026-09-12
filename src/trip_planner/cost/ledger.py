"""Dual cost ledger (spec §3.5): agent-operating cost (LLM tokens, the
FinOps-on-the-AI-system number) tracked separately from business cost (the
actual fare, the FinOps-on-the-business-process number). Both attach to the
same trace_id so "$412 in airfare, $0.03 in agent compute" is one line.

In-memory for M3, mirrored to the audit store on every write — same pattern
as guardrails/approval_gate.py. A real deployment would read this back out
of the audit store rather than out-of-process memory; the function
signatures here are what the rest of the app depends on either way.
"""
from __future__ import annotations

from typing import TypedDict

from trip_planner.audit.store import record_event
from trip_planner.config_loader import model_prices_config


class LlmCallCost(TypedDict):
    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float


class Ledger(TypedDict):
    trace_id: str
    llm_calls: list[LlmCallCost]
    agent_cost_usd: float
    business_cost_usd: float | None


_LEDGERS: dict[str, Ledger] = {}


def _get_or_create(trace_id: str) -> Ledger:
    return _LEDGERS.setdefault(
        trace_id, Ledger(trace_id=trace_id, llm_calls=[], agent_cost_usd=0.0, business_cost_usd=None)
    )


def _price_for(model: str) -> dict:
    prices = model_prices_config().get("models", {})
    if model not in prices:
        raise ValueError(f"No price entry for model={model!r} in config/model_prices.yaml")
    return prices[model]


def record_llm_usage(
    trace_id: str,
    agent: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
) -> float:
    """Records one LLM call's cost against the ledger; returns the cost in
    USD for that call. Uncached input tokens are billed at the full input
    rate; `cache_read_tokens` (already included in `input_tokens` by most
    SDKs — see the caller) are billed at the discounted cache-read rate
    instead, not double-counted."""
    price = _price_for(model)
    uncached_input_tokens = max(0, input_tokens - cache_read_tokens)
    cost_usd = (
        uncached_input_tokens * price["input_per_1m_usd"]
        + cache_read_tokens * price["cache_read_per_1m_usd"]
        + output_tokens * price["output_per_1m_usd"]
    ) / 1_000_000

    ledger = _get_or_create(trace_id)
    ledger["llm_calls"].append(
        LlmCallCost(
            agent=agent, model=model, input_tokens=input_tokens, output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens, cost_usd=round(cost_usd, 6),
        )
    )
    ledger["agent_cost_usd"] = round(ledger["agent_cost_usd"] + cost_usd, 6)

    record_event(trace_id, "llm_call_cost", {"agent": agent, "model": model, "cost_usd": round(cost_usd, 6)})
    return cost_usd


def record_business_cost(trace_id: str, fare_price_usd: float) -> None:
    """The fare ultimately considered/selected — the business-cost side of
    the ledger, tracked entirely separately from agent compute cost."""
    ledger = _get_or_create(trace_id)
    ledger["business_cost_usd"] = round(fare_price_usd, 2)
    record_event(trace_id, "business_cost_recorded", {"fare_price_usd": round(fare_price_usd, 2)})


def get_ledger(trace_id: str) -> Ledger:
    return _get_or_create(trace_id)


def _clear_all() -> None:
    """Test helper only."""
    _LEDGERS.clear()
