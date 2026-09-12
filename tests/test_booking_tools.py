"""book_flight_stub delegates to the approval gate — never books without a
granted record, and never raises (returns a structured result instead)."""
from __future__ import annotations

import pytest

from trip_planner.guardrails import approval_gate
from trip_planner.tools.booking_tools import book_flight_stub


@pytest.fixture(autouse=True)
def _clear_approval_records():
    approval_gate._clear_all()
    yield
    approval_gate._clear_all()


async def test_book_flight_blocked_without_approval():
    result = await book_flight_stub("trace-x", fare={"carrier": "AA", "price_usd": 900})
    assert result["booked"] is False
    assert result["confirmation_id"] is None
    assert "trace-x" in result["reason"]


async def test_book_flight_succeeds_after_auto_approve():
    approval_gate.auto_approve("trace-y", job_level="ic", fare={"price_usd": 400})
    result = await book_flight_stub("trace-y", fare={"carrier": "DL", "price_usd": 400})
    assert result["booked"] is True
    assert result["confirmation_id"].startswith("STUB-")
    assert result["reason"] is None
