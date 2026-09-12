"""Geocoding + weather, via the free Nominatim and Open-Meteo APIs.

No API key required for either. These are plain async functions — both the
MCP server (mcp_servers/trip_lookup_server.py) and the offline tests import
them directly; the MCP server is a thin wrapper that exposes them as tools.

Endpoints are overridable via NOMINATIM_URL / OPEN_METEO_URL (default to
the public instances) — the public Nominatim instance has a strict usage
policy meant for light use, and Open-Meteo offers a separate paid/
higher-volume API at a different base URL; production deployments commonly
point at a self-hosted Nominatim or the paid Open-Meteo tier instead.
"""
from __future__ import annotations

import os
from typing import TypedDict

import httpx

_DEFAULT_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_DEFAULT_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def _nominatim_url() -> str:
    # `or` rather than `.get(key, default)`: .env.example ships these blank
    # (meaning "use the default"), and a blank-but-present env var is still
    # a falsy "" here, not an unset key — `.get()` alone would silently
    # request "" as the URL.
    return os.environ.get("NOMINATIM_URL") or _DEFAULT_NOMINATIM_URL


def _open_meteo_url() -> str:
    return os.environ.get("OPEN_METEO_URL") or _DEFAULT_OPEN_METEO_URL


# Nominatim's usage policy requires a descriptive User-Agent identifying the app.
_HEADERS = {"User-Agent": "corporate-travel-planner-react/0.1 (internal demo)"}

_TIMEOUT = httpx.Timeout(15.0)


class GeocodeResult(TypedDict):
    city: str
    latitude: float
    longitude: float
    display_name: str


class WeatherResult(TypedDict):
    latitude: float
    longitude: float
    forecast: list[dict]


class LocationNotFoundError(Exception):
    """Raised when Nominatim has no match for the given place name."""


async def geocode(city: str) -> GeocodeResult:
    """Resolve a free-text place name to lat/lon via Nominatim.

    Raises LocationNotFoundError if no match is found — callers (the Weather
    Agent, the orchestrator) should treat that as a user-input problem, not a
    provider outage.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
        resp = await client.get(
            _nominatim_url(),
            params={"q": city, "format": "json", "limit": 1},
        )
        resp.raise_for_status()
        results = resp.json()

    if not results:
        raise LocationNotFoundError(f"No location found for {city!r}")

    match = results[0]
    return GeocodeResult(
        city=city,
        latitude=float(match["lat"]),
        longitude=float(match["lon"]),
        display_name=match.get("display_name", city),
    )


async def get_weather(latitude: float, longitude: float, days: int = 5) -> WeatherResult:
    """Fetch a short-range daily forecast for a coordinate via Open-Meteo."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            _open_meteo_url(),
            params={
                "latitude": latitude,
                "longitude": longitude,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode",
                "forecast_days": max(1, min(days, 16)),
                "timezone": "auto",
            },
        )
        resp.raise_for_status()
        payload = resp.json()

    daily = payload.get("daily", {})
    dates = daily.get("time", [])
    forecast = [
        {
            "date": dates[i],
            "temp_max_c": daily.get("temperature_2m_max", [None] * len(dates))[i],
            "temp_min_c": daily.get("temperature_2m_min", [None] * len(dates))[i],
            "precipitation_probability_pct": daily.get("precipitation_probability_max", [None] * len(dates))[i],
            "weathercode": daily.get("weathercode", [None] * len(dates))[i],
        }
        for i in range(len(dates))
    ]

    return WeatherResult(latitude=latitude, longitude=longitude, forecast=forecast)
