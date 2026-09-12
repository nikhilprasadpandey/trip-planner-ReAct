"""Dual cost ledger (spec §3.5): agent-operating cost tracked separately
from business cost, both keyed by trace_id."""
from __future__ import annotations

import pytest

from trip_planner.cost import ledger


def test_record_llm_usage_computes_cost_from_model_prices():
    cost = ledger.record_llm_usage(
        "trace-1", agent="WeatherAgent", model="gpt-4.1",
        input_tokens=1000, output_tokens=500, cache_read_tokens=0,
    )
    # gpt-4.1: $2.00/1M input, $8.00/1M output
    expected = (1000 * 2.00 + 500 * 8.00) / 1_000_000
    assert cost == pytest.approx(expected)

    snapshot = ledger.get_ledger("trace-1")
    assert snapshot["agent_cost_usd"] == pytest.approx(expected)
    assert len(snapshot["llm_calls"]) == 1


def test_cached_input_tokens_billed_at_cache_read_rate_not_double_counted():
    cost = ledger.record_llm_usage(
        "trace-2", agent="PolicyAgent", model="gpt-4.1",
        input_tokens=1000, output_tokens=0, cache_read_tokens=800,
    )
    # 200 uncached @ $2.00/1M + 800 cached @ $0.50/1M
    expected = (200 * 2.00 + 800 * 0.50) / 1_000_000
    assert cost == pytest.approx(expected)


def test_multiple_calls_accumulate_agent_cost_for_same_trace():
    ledger.record_llm_usage("trace-3", agent="WeatherAgent", model="gpt-4.1", input_tokens=100, output_tokens=100)
    ledger.record_llm_usage("trace-3", agent="FlightAgent", model="gpt-4.1", input_tokens=100, output_tokens=100)

    snapshot = ledger.get_ledger("trace-3")
    assert len(snapshot["llm_calls"]) == 2
    assert snapshot["agent_cost_usd"] > 0


def test_business_cost_tracked_separately_from_agent_cost():
    ledger.record_llm_usage("trace-4", agent="FlightAgent", model="gpt-4.1", input_tokens=100, output_tokens=100)
    ledger.record_business_cost("trace-4", 412.30)

    snapshot = ledger.get_ledger("trace-4")
    assert snapshot["business_cost_usd"] == 412.30
    assert snapshot["agent_cost_usd"] > 0
    assert snapshot["agent_cost_usd"] != snapshot["business_cost_usd"]


def test_unknown_model_raises():
    with pytest.raises(ValueError):
        ledger.record_llm_usage("trace-5", agent="X", model="not-a-real-model", input_tokens=10, output_tokens=10)
