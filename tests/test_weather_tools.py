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


def test_nominatim_url_unset_falls_back_to_public_default(monkeypatch):
    monkeypatch.delenv("NOMINATIM_URL", raising=False)
    assert weather_tools._nominatim_url() == weather_tools._DEFAULT_NOMINATIM_URL


def test_nominatim_url_blank_falls_back_to_public_default(monkeypatch):
    """Regression: .env.example ships this blank (meaning "use the
    default") — a blank-but-present env var is still falsy, not unset, so
    a plain os.environ.get(key, default) would silently request ""."""
    monkeypatch.setenv("NOMINATIM_URL", "")
    assert weather_tools._nominatim_url() == weather_tools._DEFAULT_NOMINATIM_URL


def test_nominatim_url_override_is_respected(monkeypatch):
    monkeypatch.setenv("NOMINATIM_URL", "https://nominatim.example.internal/search")
    assert weather_tools._nominatim_url() == "https://nominatim.example.internal/search"


def test_open_meteo_url_blank_falls_back_to_public_default(monkeypatch):
    monkeypatch.setenv("OPEN_METEO_URL", "")
    assert weather_tools._open_meteo_url() == weather_tools._DEFAULT_OPEN_METEO_URL


def test_open_meteo_url_override_is_respected(monkeypatch):
    monkeypatch.setenv("OPEN_METEO_URL", "https://open-meteo.example.internal/v1/forecast")
    assert weather_tools._open_meteo_url() == "https://open-meteo.example.internal/v1/forecast"


async def test_geocode_uses_the_configured_url(monkeypatch):
    monkeypatch.setenv("NOMINATIM_URL", "https://nominatim.example.internal/search")
    with respx.mock(base_url="https://nominatim.example.internal") as mock:
        mock.get("/search").mock(
            return_value=Response(200, json=[{"lat": "1.0", "lon": "2.0", "display_name": "Test"}])
        )
        result = await weather_tools.geocode("Somewhere")
    assert result["latitude"] == 1.0
