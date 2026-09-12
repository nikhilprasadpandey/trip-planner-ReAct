"""Offline tests for the provider-swappable flight search (spec §3.2/§4:
graceful degradation on provider outage/quota exhaustion, no live API calls)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx
from httpx import Response
from pydantic import TypeAdapter

from trip_planner import config_loader
from trip_planner.tools import flight_tools
from trip_planner.tools.flight_tools import FlightSearchResult

FIXTURES = Path(__file__).parent / "fixtures"

# The MCP server (mcp_servers/trip_lookup_server.py) validates search_flights'
# return value against this exact schema before it ever reaches an agent —
# calling flight_tools.search_flights() directly, as every test below does,
# bypasses that validation. _assert_mcp_would_accept re-applies it, so a
# TypedDict/schema mismatch (e.g. a bool where FlightSearchResult expects a
# str) fails here instead of only failing live against real provider data.
_RESULT_ADAPTER = TypeAdapter(FlightSearchResult)


def _assert_mcp_would_accept(result: dict) -> None:
    _RESULT_ADAPTER.validate_python(result)


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


async def test_duffel_happy_path(monkeypatch):
    monkeypatch.setenv("FLIGHT_PROVIDER", "duffel")
    monkeypatch.setenv("DUFFEL_ACCESS_TOKEN", "duffel_test_fake_token")

    with respx.mock(base_url="https://api.duffel.com") as mock:
        mock.post("/air/offer_requests").mock(
            return_value=Response(201, json=_load("duffel_offer_request_response.json"))
        )
        result = await flight_tools.search_flights("SFO", "AUS", "2026-10-01")

    assert result["available"] is True
    assert result["provider"] == "duffel"
    # sorted by price ascending
    assert result["fares"][0]["carrier"] == "DL"
    assert result["fares"][0]["price_usd"] == 389.00
    assert all(f["price_is_estimated"] is False for f in result["fares"])
    # regression: Duffel's `allowed` is a real bool; fare_rules must be a
    # human-readable string, not that bool passed straight through
    assert all(isinstance(f["fare_rules"], str) for f in result["fares"])
    _assert_mcp_would_accept(result)


async def test_duffel_handles_null_conditions_and_owner(monkeypatch):
    """Regression: real Duffel offers commonly carry explicit `null`s for
    conditions/owner fields that don't apply to a given offer — a
    `.get(x, {})` on a key whose *value* is None still returns None, and
    chaining `.get()` on that raised 'NoneType has no attribute get' in
    production against live Duffel data (caught during acceptance testing,
    not by the original fixture, which only used clean data)."""
    monkeypatch.setenv("FLIGHT_PROVIDER", "duffel")
    monkeypatch.setenv("DUFFEL_ACCESS_TOKEN", "duffel_test_fake_token")

    with respx.mock(base_url="https://api.duffel.com") as mock:
        mock.post("/air/offer_requests").mock(
            return_value=Response(201, json=_load("duffel_offer_request_response_null_conditions.json"))
        )
        result = await flight_tools.search_flights("SFO", "AUS", "2026-10-01")

    assert result["available"] is True
    fares_by_price = {f["price_usd"]: f for f in result["fares"]}
    assert fares_by_price[455.10]["carrier"] == "UA"
    assert fares_by_price[455.10]["fare_rules"] == "unknown"
    assert fares_by_price[470.00]["carrier"] == "unknown"
    assert fares_by_price[470.00]["fare_rules"] == "unknown"
    _assert_mcp_would_accept(result)


async def test_aviationstack_happy_path(monkeypatch):
    monkeypatch.setenv("FLIGHT_PROVIDER", "aviationstack")
    monkeypatch.setenv("AVIATIONSTACK_API_KEY", "fake_key")

    with respx.mock(base_url="https://api.aviationstack.com/v1") as mock:
        mock.get("/flights").mock(
            return_value=Response(200, json=_load("aviationstack_flights_response.json"))
        )
        result = await flight_tools.search_flights("SFO", "AUS", "2026-10-01")

    assert result["available"] is True
    assert result["provider"] == "aviationstack"
    assert result["fares"][0]["carrier"] == "UA"
    assert result["fares"][0]["price_is_estimated"] is True
    _assert_mcp_would_accept(result)


async def test_aviationstack_quota_exhausted_degrades_gracefully(monkeypatch):
    """Spec §4/§8: on provider quota exhaustion the Flight Agent must return
    a clear 'pricing unavailable' observation, never hang or raise."""
    monkeypatch.setenv("FLIGHT_PROVIDER", "aviationstack")
    monkeypatch.setenv("AVIATIONSTACK_API_KEY", "fake_key")

    with respx.mock(base_url="https://api.aviationstack.com/v1") as mock:
        mock.get("/flights").mock(
            return_value=Response(200, json=_load("aviationstack_quota_error_response.json"))
        )
        result = await flight_tools.search_flights("SFO", "AUS", "2026-10-01")

    assert result["available"] is False
    assert "usage_limit_reached" in result["reason"]
    assert result["fares"] == []


async def test_missing_provider_credentials_degrades_gracefully(monkeypatch):
    monkeypatch.setenv("FLIGHT_PROVIDER", "duffel")
    monkeypatch.delenv("DUFFEL_ACCESS_TOKEN", raising=False)

    result = await flight_tools.search_flights("SFO", "AUS", "2026-10-01")

    assert result["available"] is False
    assert "DUFFEL_ACCESS_TOKEN" in result["reason"]


async def test_provider_timeout_degrades_gracefully(monkeypatch):
    import httpx

    monkeypatch.setenv("FLIGHT_PROVIDER", "duffel")
    monkeypatch.setenv("DUFFEL_ACCESS_TOKEN", "duffel_test_fake_token")

    with respx.mock(base_url="https://api.duffel.com") as mock:
        mock.post("/air/offer_requests").mock(side_effect=httpx.ConnectTimeout("boom"))
        result = await flight_tools.search_flights("SFO", "AUS", "2026-10-01")

    assert result["available"] is False
    assert result["provider"] == "duffel"

