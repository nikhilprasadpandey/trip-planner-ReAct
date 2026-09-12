"""Exact-match route cache (spec §3.9, §8): a repeated identical route
search must be served from cache with zero additional flight-API/agent
calls — verified here at the cache-storage level."""
from __future__ import annotations

from trip_planner.cache import route_cache


def test_miss_then_hit_returns_stored_result_and_saved_cost():
    assert route_cache.get("SFO", "AUS", "2026-10-01", "economy") is None

    fares = {"available": True, "fares": [{"carrier": "AA", "price_usd": 400}]}
    route_cache.set("SFO", "AUS", "2026-10-01", "economy", fares, agent_cost_usd=0.004)

    entry = route_cache.get("SFO", "AUS", "2026-10-01", "economy")
    assert entry is not None
    assert entry["result"] == fares
    assert entry["agent_cost_saved_usd"] == 0.004


def test_cache_key_is_case_insensitive_on_airport_codes():
    fares = {"available": True, "fares": []}
    route_cache.set("sfo", "aus", "2026-10-01", "economy", fares, agent_cost_usd=0.001)
    assert route_cache.get("SFO", "AUS", "2026-10-01", "economy") is not None


def test_different_cabin_class_is_a_different_cache_entry():
    route_cache.set("SFO", "AUS", "2026-10-01", "economy", {"fares": ["e"]}, agent_cost_usd=0.001)
    assert route_cache.get("SFO", "AUS", "2026-10-01", "business") is None


def test_different_date_is_a_different_cache_entry():
    route_cache.set("SFO", "AUS", "2026-10-01", "economy", {"fares": ["a"]}, agent_cost_usd=0.001)
    assert route_cache.get("SFO", "AUS", "2026-10-02", "economy") is None
