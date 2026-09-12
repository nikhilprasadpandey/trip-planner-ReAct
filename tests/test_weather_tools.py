"""Offline tests for geocoding + weather (Nominatim + Open-Meteo), mocked
via respx — no live network calls."""
from __future__ import annotations

import pytest
import respx
from httpx import Response

from trip_planner.tools import weather_tools


async def test_geocode_happy_path():
    with respx.mock(base_url="https://nominatim.openstreetmap.org") as mock:
        mock.get("/search").mock(
            return_value=Response(
                200,
                json=[{"lat": "30.2672", "lon": "-97.7431", "display_name": "Austin, Texas, USA"}],
            )
        )
        result = await weather_tools.geocode("Austin, TX")

    assert result["latitude"] == pytest.approx(30.2672)
    assert result["longitude"] == pytest.approx(-97.7431)
    assert "Austin" in result["display_name"]


async def test_geocode_not_found_raises():
    with respx.mock(base_url="https://nominatim.openstreetmap.org") as mock:
        mock.get("/search").mock(return_value=Response(200, json=[]))
        with pytest.raises(weather_tools.LocationNotFoundError):
            await weather_tools.geocode("Nowhereville")


async def test_get_weather_happy_path():
    payload = {
        "daily": {
            "time": ["2026-10-01", "2026-10-02"],
            "temperature_2m_max": [28.5, 27.1],
            "temperature_2m_min": [18.2, 17.9],
            "precipitation_probability_max": [10, 40],
            "weathercode": [1, 61],
        }
    }
    with respx.mock(base_url="https://api.open-meteo.com") as mock:
        mock.get("/v1/forecast").mock(return_value=Response(200, json=payload))
        result = await weather_tools.get_weather(30.2672, -97.7431, days=2)

    assert len(result["forecast"]) == 2
    assert result["forecast"][0]["date"] == "2026-10-01"
    assert result["forecast"][1]["precipitation_probability_pct"] == 40
