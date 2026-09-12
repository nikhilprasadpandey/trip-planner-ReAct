"""FastAPI gateway route-binding tests — catches parameter-binding bugs
that unit tests of the underlying logic can't (e.g. an untyped `request`
param meant for slowapi's rate limiter being mis-bound by FastAPI as a
required query string, which made every POST /trip-requests 422 regardless
of a valid body)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from trip_planner.api import main as api_main


def test_trip_requests_does_not_422_on_valid_body(monkeypatch):
    async def fake_run_trip_planning(request, trace_id=None):
        return {"trace_id": "fake-trace", "request": request, "status": "ok"}

    monkeypatch.setattr(api_main, "run_trip_planning", fake_run_trip_planning)
    client = TestClient(api_main.app)

    resp = client.post(
        "/trip-requests",
        json={
            "destination_city": "Austin, TX",
            "origin_airport": "sfo",
            "destination_airport": "aus",
            "departure_date": "2026-11-10",
        },
        headers={"X-Employee-Id": "employee-ic-001"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["trace_id"] == "fake-trace"
    assert body["request"]["origin_airport"] == "SFO"  # uppercased
    assert body["request"]["job_level"] == "ic"


def test_trip_requests_rejects_unknown_persona():
    client = TestClient(api_main.app)
    resp = client.post(
        "/trip-requests",
        json={
            "destination_city": "Austin, TX",
            "origin_airport": "SFO",
            "destination_airport": "AUS",
            "departure_date": "2026-11-10",
        },
        headers={"X-Employee-Id": "not-a-real-employee"},
    )
    assert resp.status_code == 401
