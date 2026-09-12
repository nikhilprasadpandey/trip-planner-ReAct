"""MCP server #1 (spec §3.2a): geocode, get_weather, search_flights — the
read-only lookups a trip request needs before anything gets booked.

Read-only tools only — no mutating action lives here (that's the separate
booking_server.py, deliberately isolated so the one write action in the
system is easy to reason about and gate).

Run standalone for local testing:
    python -m trip_planner.mcp_servers.trip_lookup_server
Agents normally reach this via mcp_servers/mcp_client.py, which spawns it
over stdio.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from trip_planner.tools.flight_tools import CabinClass, FlightSearchResult
from trip_planner.tools.flight_tools import search_flights as _search_flights
from trip_planner.tools.weather_tools import (
    GeocodeResult,
    LocationNotFoundError,
    WeatherResult,
    geocode as _geocode,
    get_weather as _get_weather,
)

mcp = FastMCP("trip-lookup")


@mcp.tool()
async def geocode(city: str) -> GeocodeResult:
    """Resolve a free-text place name (city, airport, address) to latitude/longitude.

    Args:
        city: Free-text place name, e.g. "Austin, TX" or "Austin-Bergstrom Airport".
    """
    try:
        return await _geocode(city)
    except LocationNotFoundError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
async def get_weather(latitude: float, longitude: float, days: int = 5) -> WeatherResult:
    """Get a short-range daily forecast for a coordinate.

    Args:
        latitude: Latitude in decimal degrees.
        longitude: Longitude in decimal degrees.
        days: Number of forecast days to return (1-16, default 5).
    """
    return await _get_weather(latitude, longitude, days)


@mcp.tool()
async def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    cabin_class: CabinClass = "economy",
) -> FlightSearchResult:
    """Search flight fares between two IATA airport codes on a given date.

    Uses the provider configured in config/flight_provider.yaml (duffel test
    mode or aviationstack live). On provider outage or quota exhaustion,
    returns `available: False` with a `reason` — never raises.

    Args:
        origin: 3-letter IATA origin airport code, e.g. "SFO".
        destination: 3-letter IATA destination airport code, e.g. "AUS".
        departure_date: ISO date, e.g. "2026-10-01".
        cabin_class: One of economy, premium_economy, business, first.
    """
    return await _search_flights(origin, destination, departure_date, cabin_class)


if __name__ == "__main__":
    mcp.run()
