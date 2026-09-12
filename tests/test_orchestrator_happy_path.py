"""Orchestrator tests.

`_extract_tool_result` and the graph's shape are tested offline (no LLM, no
network). A full end-to-end run through real ReAct agents needs a live
OPENAI_API_KEY (and ideally DUFFEL_ACCESS_TOKEN) — that integration test
is skipped unless both are present, so `pytest` stays fully offline by
default per the spec's dry-run requirement.
"""
from __future__ import annotations

import os

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from trip_planner.orchestrator.graph import _extract_tool_result, build_graph
from trip_planner.orchestrator.graph import run_trip_planning
from trip_planner.orchestrator.state import TripRequest


def test_extract_tool_result_returns_latest_matching_tool_call():
    messages = [
        HumanMessage(content="plan my trip"),
        AIMessage(content="", tool_calls=[]),
        ToolMessage(content='{"latitude": 30.2, "longitude": -97.7}', name="geocode", tool_call_id="1"),
        ToolMessage(content='{"forecast": []}', name="get_weather", tool_call_id="2"),
    ]

    geo = _extract_tool_result(messages, "geocode")
    wx = _extract_tool_result(messages, "get_weather")
    missing = _extract_tool_result(messages, "search_flights")

    assert geo == {"latitude": 30.2, "longitude": -97.7}
    assert wx == {"forecast": []}
    assert missing is None


def test_extract_tool_result_handles_the_real_mcp_content_block_shape():
    """Regression: the real MCP + langchain_openai stack delivers
    ToolMessage.content as [{"type": "text", "text": "<json>"}], not a plain
    string — caught live, where this silently made every successful
    weather/flight tool call look like "no result"."""
    messages = [
        ToolMessage(
            content=[{"type": "text", "text": '{"latitude": 30.2, "longitude": -97.7}', "id": "lc_1"}],
            name="geocode",
            tool_call_id="1",
        ),
    ]
    assert _extract_tool_result(messages, "geocode") == {"latitude": 30.2, "longitude": -97.7}


def test_extract_tool_result_falls_back_to_raw_on_non_json_content():
    messages = [ToolMessage(content="not json", name="geocode", tool_call_id="1")]
    assert _extract_tool_result(messages, "geocode") == {"raw": "not json"}


def test_graph_has_expected_node_shape():
    graph = build_graph()
    node_names = set(graph.get_graph().nodes.keys())
    assert {"weather", "flight_search"} <= node_names


@pytest.mark.skipif(
    not (os.environ.get("OPENAI_API_KEY") and os.environ.get("DUFFEL_ACCESS_TOKEN")),
    reason="requires a live OPENAI_API_KEY + DUFFEL_ACCESS_TOKEN for a real end-to-end run",
)
async def test_run_trip_planning_end_to_end_live():
    request: TripRequest = {
        "employee_id": "employee-ic-001",
        "job_level": "ic",
        "destination_city": "Austin, TX",
        "origin_airport": "SFO",
        "destination_airport": "AUS",
        "departure_date": "2026-10-01",
        "cabin_class": "economy",
    }
    final_state = await run_trip_planning(request)
    assert final_state["trace_id"]
    assert "weather" in final_state or "flight_search" in final_state
