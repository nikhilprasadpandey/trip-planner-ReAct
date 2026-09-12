"""Flight Agent — native tool-calling ReAct agent scoped to flight-search only.

Returns candidate fares with carrier, price, cabin class, and fare rules
(spec §3.1). The Policy Agent (M2) re-queries this agent via the orchestrator
for a cheaper/lower-cabin alternative when the first candidate is
out-of-policy — that reflection loop lives in orchestrator/graph.py, not here;
this agent just answers "find me fares" requests.
"""
from __future__ import annotations

from trip_planner.agents.base import AllowListedReActAgent
from trip_planner.mcp_servers.mcp_client import load_tools


class FlightAgent(AllowListedReActAgent):
    ALLOWED_TOOLS = frozenset({"search_flights"})
    SYSTEM_PROMPT = (
        "You are the Flight Agent for a corporate travel planner. Given an "
        "origin, destination, and date, search fares and report candidates "
        "sorted by price: carrier, price in USD, cabin class, and fare "
        "rules. If pricing is unavailable, say so plainly and do not "
        "invent a price."
    )

    @classmethod
    def mcp_server_name(cls) -> str:
        return "trip_lookup"


async def build_flight_agent() -> FlightAgent:
    tools = await load_tools(FlightAgent.mcp_server_name(), FlightAgent.ALLOWED_TOOLS)
    return FlightAgent(tools)
