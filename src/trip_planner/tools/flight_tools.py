"""Provider-swappable flight search: Duffel (test mode) / Aviationstack (live).

Amadeus's Self-Service sandbox was decommissioned 2026-07-17 — not used here.
The active provider is selected by config/flight_provider.yaml (`active:`),
overridable via the FLIGHT_PROVIDER env var. Callers (the Flight Agent, via
the search_flights MCP tool) only ever see `search_flights()` below — provider
response shapes never leak past this module.

Known limitation, flagged for the build spec's author: Aviationstack is a
flight-schedule/tracking API, not a fare-pricing API — it has no price field.
For the "live demo" path we still return real flight/carrier data from it,
but the fare price is a heuristic estimate (`price_is_estimated: True`), not
a quoted fare. Duffel test mode returns real fare-shaped offers (sandbox
prices) and is the source to prefer for anything demonstrating the
policy/approval-gate logic against an actual price.
"""
from __future__ import annotations

import os
from typing import Literal, TypedDict

import httpx

from trip_planner.config_loader import active_flight_provider, flight_provider_config

CabinClass = Literal["economy", "premium_economy", "business", "first"]


class Fare(TypedDict):
    carrier: str
    price_usd: float
    price_is_estimated: bool
    cabin_class: str
    fare_rules: str
    provider: str


class FlightSearchResult(TypedDict):
    origin: str
    destination: str
    departure_date: str
    available: bool
    reason: str | None          # set when available is False (outage/quota/etc.)
    provider: str
    fares: list[Fare]


class FlightProviderError(Exception):
    """Raised internally by a provider adapter; always caught in search_flights."""


# --------------------------------------------------------------------------- #
# Duffel (test mode) — real API shape, sandbox data, safe to hammer in dev.
# --------------------------------------------------------------------------- #

async def _search_duffel(origin: str, destination: str, departure_date: str, cabin_class: CabinClass) -> list[Fare]:
    token = os.environ.get("DUFFEL_ACCESS_TOKEN")
    if not token:
        raise FlightProviderError("DUFFEL_ACCESS_TOKEN is not set")

    cfg = flight_provider_config()["providers"]["duffel"]
    headers = {
        "Authorization": f"Bearer {token}",
        "Duffel-Version": cfg.get("api_version", "v2"),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {
        "data": {
            "slices": [{"origin": origin, "destination": destination, "departure_date": departure_date}],
            "passengers": [{"type": "adult"}],
            "cabin_class": cabin_class,
        }
    }

    timeout = httpx.Timeout(cfg.get("timeout_seconds", 15))
    async with httpx.AsyncClient(base_url=cfg["base_url"], headers=headers, timeout=timeout) as client:
        req_resp = await client.post("/air/offer_requests", json=body, params={"return_offers": "true"})
        req_resp.raise_for_status()
        offers = req_resp.json().get("data", {}).get("offers", [])

    fares: list[Fare] = []
    for offer in offers[:10]:
        # Duffel offers commonly carry explicit `null`s for conditions that
        # don't apply to a given offer (not just missing keys) — `.get(x, {})`
        # doesn't guard against that, only against the key being absent.
        owner = offer.get("owner") or {}
        conditions = offer.get("conditions") or {}
        change_rule = conditions.get("change_before_departure") or {}
        # Duffel's `allowed` is a real boolean, not a string — the MCP
        # server validates FlightSearchResult against its TypedDict via
        # pydantic, and a raw bool there fails that validation (caught live;
        # calling search_flights() directly in tests bypasses that
        # validation layer entirely, so a plain unit test won't catch this
        # class of bug — see tests/test_flight_tools.py's
        # _assert_mcp_would_accept, which re-applies that same schema check).
        changes_allowed = change_rule.get("allowed")
        if changes_allowed is None:
            fare_rules = "unknown"
        else:
            fare_rules = "changes allowed" if changes_allowed else "changes not allowed"
        fares.append(
            Fare(
                carrier=owner.get("iata_code") or owner.get("name") or "unknown",
                price_usd=round(float(offer.get("total_amount", 0.0)), 2),
                price_is_estimated=False,
                cabin_class=cabin_class,
                fare_rules=fare_rules,
                provider="duffel",
            )
        )
    return fares


# --------------------------------------------------------------------------- #
# Aviationstack (live) — flight schedule/status data; no native pricing.
# --------------------------------------------------------------------------- #

# Rough, clearly-labeled per-mile domestic/international heuristics used only
# to give the Policy Agent something price-shaped to evaluate against the
# live provider. Not a substitute for a real fare-pricing API.
_ESTIMATED_BASE_FARE_USD = {"economy": 250, "premium_economy": 450, "business": 1400, "first": 3000}


async def _search_aviationstack(
    origin: str, destination: str, departure_date: str, cabin_class: CabinClass
) -> list[Fare]:
    key = os.environ.get("AVIATIONSTACK_API_KEY")
    if not key:
        raise FlightProviderError("AVIATIONSTACK_API_KEY is not set")

    cfg = flight_provider_config()["providers"]["aviationstack"]
    timeout = httpx.Timeout(cfg.get("timeout_seconds", 15))
    async with httpx.AsyncClient(base_url=cfg["base_url"], timeout=timeout) as client:
        resp = await client.get(
            "/flights",
            params={
                "access_key": key,
                "dep_iata": origin,
                "arr_iata": destination,
                "flight_date": departure_date,
            },
        )
        resp.raise_for_status()
        payload = resp.json()

    if "error" in payload:
        # Aviationstack reports quota exhaustion / auth errors in a 200 body.
        raise FlightProviderError(str(payload["error"]))

    flights = payload.get("data", [])
    base = _ESTIMATED_BASE_FARE_USD.get(cabin_class, _ESTIMATED_BASE_FARE_USD["economy"])
    fares: list[Fare] = []
    for f in flights[:10]:
        carrier = (f.get("airline") or {}).get("iata") or "unknown"
        fares.append(
            Fare(
                carrier=carrier,
                price_usd=float(base),
                price_is_estimated=True,
                cabin_class=cabin_class,
                fare_rules="unavailable (aviationstack has no fare-rules data)",
                provider="aviationstack",
            )
        )
    return fares


_PROVIDERS = {"duffel": _search_duffel, "aviationstack": _search_aviationstack}


async def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    cabin_class: CabinClass = "economy",
) -> FlightSearchResult:
    """Search fares via the active provider. Never raises — on any provider
    failure (timeout, missing key, quota exhausted, HTTP error) returns
    `available: False` with a clear `reason`, per the graceful-degradation
    requirement, so the Flight Agent/orchestrator never hangs or crashes.
    """
    provider = active_flight_provider()
    search_fn = _PROVIDERS.get(provider)
    if search_fn is None:
        return FlightSearchResult(
            origin=origin, destination=destination, departure_date=departure_date,
            available=False, reason=f"unknown flight provider configured: {provider!r}",
            provider=provider, fares=[],
        )

    try:
        fares = await search_fn(origin, destination, departure_date, cabin_class)
    except (FlightProviderError, httpx.HTTPError, httpx.TimeoutException, KeyError, ValueError) as exc:
        return FlightSearchResult(
            origin=origin, destination=destination, departure_date=departure_date,
            available=False, reason=f"pricing unavailable ({provider}): {exc}",
            provider=provider, fares=[],
        )

    if not fares:
        return FlightSearchResult(
            origin=origin, destination=destination, departure_date=departure_date,
            available=False, reason=f"no fares returned by {provider} for this route/date",
            provider=provider, fares=[],
        )

    return FlightSearchResult(
        origin=origin, destination=destination, departure_date=departure_date,
        available=True, reason=None, provider=provider,
        fares=sorted(fares, key=lambda f: f["price_usd"]),
    )
