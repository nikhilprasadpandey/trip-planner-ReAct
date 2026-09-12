"""Weather Agent — reused as-is across domains (proves the "swap the domain,
reuse the specialist" value of the architecture, per spec §3.1). Scoped to
geocode + get_weather only.
"""
from __future__ import annotations

from trip_planner.agents.base import AllowListedReActAgent
from trip_planner.mcp_servers.mcp_client import load_tools


class WeatherAgent(AllowListedReActAgent):
    ALLOWED_TOOLS = frozenset({"geocode", "get_weather"})
    SYSTEM_PROMPT = (
        "You are the Weather Agent for a corporate travel planner. Given a "
        "destination city, always call geocode then get_weather — never "
        "decline or reason about date feasibility before calling the tools; "
        "you do not reliably know the current date on your own, so trust "
        "the caller's stated 'today' date, not your own assumption. "
        "get_weather returns a short-range forecast (~16 days ahead of "
        "today) starting from today, not from a specific requested date — "
        "if the trip date falls within that window, report the forecast "
        "for it; if it falls beyond the returned range, say plainly that "
        "the trip is too far out for a forecast yet and report the current "
        "near-term conditions instead, rather than returning nothing. Be "
        "concise and factual; state temperatures in Celsius and "
        "precipitation chance as a percentage."
    )

    @classmethod
    def mcp_server_name(cls) -> str:
        return "free_tools"


async def build_weather_agent() -> WeatherAgent:
    tools = await load_tools(WeatherAgent.mcp_server_name(), WeatherAgent.ALLOWED_TOOLS)
    return WeatherAgent(tools)
