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
        "destination city, geocode it and report the short-range forecast "
        "for the trip dates. Be concise and factual; state temperatures in "
        "Celsius and precipitation chance as a percentage."
    )

    @classmethod
    def mcp_server_name(cls) -> str:
        return "free_tools"


async def build_weather_agent() -> WeatherAgent:
    tools = await load_tools(WeatherAgent.mcp_server_name(), WeatherAgent.ALLOWED_TOOLS)
    return WeatherAgent(tools)
