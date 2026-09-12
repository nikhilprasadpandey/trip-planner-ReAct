"""MCP server #2 (spec §3.2b): the stub booking system.

Exposes a single mutating tool, `book_flight` — the one write action in the
whole system. Deliberately isolated in its own server (higher-trust,
higher-scrutiny per spec §3.7): the trip-lookup server never has access to
this, and this server never needs flight-search or weather logic.

`book_flight` never books anything without an approval record for the given
trace_id — see guardrails/approval_gate.py, which this delegates to via
tools/booking_tools.py.

Run standalone: python -m trip_planner.mcp_servers.booking_server
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from trip_planner.tools.booking_tools import BookingResult
from trip_planner.tools.booking_tools import book_flight_stub as _book_flight_stub

mcp = FastMCP("booking-system")


@mcp.tool()
async def book_flight(trace_id: str, fare: dict) -> BookingResult:
    """Book a previously-searched fare. Requires an approval record to
    already exist for `trace_id` (auto-approved, or explicitly granted) —
    returns `booked: False` with a reason otherwise. Never raises.

    Args:
        trace_id: The trace_id of the trip-planning request this fare came from.
        fare: The fare object (carrier, price_usd, cabin_class, ...) to book.
    """
    return await _book_flight_stub(trace_id, fare)


if __name__ == "__main__":
    mcp.run()
