"""LangGraph orchestrator — M1 core flow: weather (geocode -> forecast, one
ReAct loop) -> flight_search. Policy-check node, the approval gate, and the
Policy<->Flight reflection loop are added in M2 without changing this file's
shape (new node + new conditional edge).
"""
from __future__ import annotations

import json
import uuid
from functools import lru_cache

from langchain_core.messages import ToolMessage
from langgraph.graph import END, StateGraph

from trip_planner.agents.flight_agent import build_flight_agent
from trip_planner.agents.weather_agent import build_weather_agent
from trip_planner.audit.jsonl_sink import record_event
from trip_planner.orchestrator.state import TripRequest, TripState


def _extract_tool_result(messages: list, tool_name: str) -> dict | None:
    """Pull the most recent structured result for `tool_name` out of a ReAct
    agent's message trace, so orchestrator state carries structured data
    (for the Policy Agent, audit trail) rather than only the agent's prose
    answer."""
    for message in reversed(messages):
        if isinstance(message, ToolMessage) and getattr(message, "name", None) == tool_name:
            content = message.content
            if isinstance(content, str):
                try:
                    return json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    return {"raw": content}
            if isinstance(content, dict):
                return content
    return None


async def weather_node(state: TripState) -> dict:
    request = state["request"]
    agent = await build_weather_agent()
    result = await agent.ainvoke(
        f"Look up the weather for a trip to {request['destination_city']} "
        f"around {request['departure_date']}."
    )
    messages = result["messages"]
    updates: dict = {}
    if (geo := _extract_tool_result(messages, "geocode")) is not None:
        updates["geocode"] = geo
    if (wx := _extract_tool_result(messages, "get_weather")) is not None:
        updates["weather"] = wx

    record_event(state["trace_id"], "weather_node_complete", {"request": request, "result": updates})
    return updates


async def flight_node(state: TripState) -> dict:
    request = state["request"]
    agent = await build_flight_agent()
    result = await agent.ainvoke(
        f"Find fares from {request['origin_airport']} to {request['destination_airport']} "
        f"on {request['departure_date']}, cabin class "
        f"{request.get('cabin_class', 'economy')}."
    )
    messages = result["messages"]
    updates: dict = {}
    if (fares := _extract_tool_result(messages, "search_flights")) is not None:
        updates["flight_search"] = fares
        if fares.get("available") is False:
            updates["status"] = "degraded"
            updates["errors"] = [*state.get("errors", []), fares.get("reason", "flight search unavailable")]

    record_event(state["trace_id"], "flight_node_complete", {"request": request, "result": updates})
    return updates


@lru_cache(maxsize=1)
def build_graph():
    graph = StateGraph(TripState)
    graph.add_node("weather", weather_node)
    graph.add_node("flight_search", flight_node)
    graph.set_entry_point("weather")
    graph.add_edge("weather", "flight_search")
    graph.add_edge("flight_search", END)
    return graph.compile()


async def run_trip_planning(request: TripRequest, trace_id: str | None = None) -> TripState:
    """Entry point used by the API gateway (and directly by tests/Streamlit
    in M1, before the gateway is the only caller in M3)."""
    trace_id = trace_id or str(uuid.uuid4())
    initial_state: TripState = {
        "trace_id": trace_id,
        "request": request,
        "status": "ok",
        "errors": [],
    }
    record_event(trace_id, "request_received", {"request": request})

    final_state = await build_graph().ainvoke(initial_state)

    record_event(trace_id, "request_completed", {"status": final_state.get("status", "ok")})
    return final_state
