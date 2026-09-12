"""Offline tests for the provider-swappable flight search (spec §3.2/§4:
graceful degradation on provider outage/quota exhaustion, no live API calls)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx
from httpx import Response

from trip_planner import config_loader
from trip_planner.tools import flight_tools

FIXTURES = Path(__file__).parent / "fixtures"


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

