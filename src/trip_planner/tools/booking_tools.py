"""The one write action in the system (spec §3.2b) — stubbed for the demo.

Logic lives here, separate from the MCP tool decorator in
mcp_servers/booking_server.py, matching the flight_tools.py/weather_tools.py
pattern. `book_flight_stub` is a stub: it never calls a real booking
system, but it does enforce the real guardrail — no approval record, no
"booking" — via guardrails/approval_gate.py.
"""
from __future__ import annotations

import uuid
from typing import TypedDict

from trip_planner.guardrails.approval_gate import ApprovalRequiredError, require_approval_for_booking


class BookingResult(TypedDict):
    booked: bool
    confirmation_id: str | None
    reason: str | None


async def book_flight_stub(trace_id: str, fare: dict) -> BookingResult:
    """Never raises to the caller — mirrors the graceful-degradation shape
    used elsewhere (flight_tools.search_flights), so a blocked booking is a
    clear structured result, not an exception the MCP layer has to translate."""
    try:
        require_approval_for_booking(trace_id)
    except ApprovalRequiredError as exc:
        return BookingResult(booked=False, confirmation_id=None, reason=str(exc))

    # Stub booking system — no real reservation is made.
    confirmation_id = f"STUB-{uuid.uuid4().hex[:10].upper()}"
    return BookingResult(booked=True, confirmation_id=confirmation_id, reason=None)
