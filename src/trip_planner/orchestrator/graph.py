"""LangGraph orchestrator — weather -> flight_search -> policy_check, with a
reflection edge (spec §3.1): if the Policy Agent finds the cheapest fare
out-of-policy and a lower cabin class is available, loop back to
flight_search up to `max_reflection_retries` times (config/guardrails.yaml)
before giving up and routing to approval.
"""
from __future__ import annotations

import json
import uuid
from functools import lru_cache

from langchain_core.messages import ToolMessage
from langgraph.graph import END, StateGraph

from trip_planner.agents.flight_agent import build_flight_agent
from trip_planner.agents.policy_agent import evaluate_fare
from trip_planner.agents.weather_agent import build_weather_agent
from trip_planner.audit.jsonl_sink import record_event
from trip_planner.config_loader import guardrails_config
from trip_planner.guardrails import approval_gate
from trip_planner.guardrails.prompt_injection import check_prompt_injection
from trip_planner.guardrails.thresholds import next_lower_cabin_class
from trip_planner.observability.tracing import (
    end_request_trace,
    log_guardrail_event,
    log_span,
    start_request_trace,
)
from trip_planner.orchestrator.state import TripRequest, TripState


class PromptInjectionDetectedError(Exception):
    pass


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
    log_span(state["trace_id"], "agent:weather", input=request, output=updates)
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
    log_span(state["trace_id"], "agent:flight", input=request, output=updates)
    return updates


async def policy_check_node(state: TripState) -> dict:
    """Evaluate the cheapest available fare against policy; either
    auto-approve, request a cheaper/lower-cabin alternative (reflection,
    spec §3.1), or route to approval (spec §3.4). Setting `approval` in the
    returned update is how `route_after_policy_check` knows this branch is
    finished (vs. looping back to flight_search)."""
    request = state["request"]
    trace_id = state["trace_id"]
    flight = state.get("flight_search")

    if not flight or not flight.get("available") or not flight.get("fares"):
        return {
            "policy_evaluation": {"skipped": True, "reason": "no fare available to evaluate"},
            "approval": {"status": "not_applicable"},
        }

    cheapest_fare = flight["fares"][0]
    evaluation = await evaluate_fare(
        job_level=request["job_level"],
        fare=cheapest_fare,
        is_international=request.get("is_international", False),
    )
    log_span(trace_id, "agent:policy", input=cheapest_fare, output=evaluation)

    if evaluation["threshold"]["within_policy"]:
        approval_gate.auto_approve(trace_id, request["job_level"], cheapest_fare)
        return {"policy_evaluation": evaluation, "approval": approval_gate.get_approval(trace_id)}

    reflection_count = state.get("reflection_count", 0)
    max_retries = guardrails_config().get("max_reflection_retries", 2)
    lower_cabin = next_lower_cabin_class(cheapest_fare["cabin_class"])

    if reflection_count < max_retries and lower_cabin is not None:
        log_guardrail_event(
            trace_id, "policy_reflection_retry",
            {"reflection_count": reflection_count + 1, "from_cabin": cheapest_fare["cabin_class"], "to_cabin": lower_cabin},
        )
        record_event(trace_id, "policy_reflection_retry", {"to_cabin": lower_cabin})
        return {
            "policy_evaluation": evaluation,
            "reflection_count": reflection_count + 1,
            "request": {**request, "cabin_class": lower_cabin},
        }

    approval_gate.create_pending_approval(
        trace_id, request["job_level"], cheapest_fare, evaluation["threshold"]["approver_role"]
    )
    log_guardrail_event(trace_id, "approval_required", {"approver_role": evaluation["threshold"]["approver_role"]})
    return {"policy_evaluation": evaluation, "approval": approval_gate.get_approval(trace_id)}


def route_after_policy_check(state: TripState) -> str:
    return "finish" if "approval" in state else "retry"


@lru_cache(maxsize=1)
def build_graph():
    graph = StateGraph(TripState)
    graph.add_node("weather", weather_node)
    graph.add_node("flight_search", flight_node)
    graph.add_node("policy_check", policy_check_node)

    graph.set_entry_point("weather")
    graph.add_edge("weather", "flight_search")
    graph.add_edge("flight_search", "policy_check")
    graph.add_conditional_edges("policy_check", route_after_policy_check, {"retry": "flight_search", "finish": END})

    return graph.compile()


async def run_trip_planning(request: TripRequest, trace_id: str | None = None) -> TripState:
    """Entry point used by the API gateway. Runs the input prompt-injection
    guardrail (spec §3.4) before anything else — a suspicious request is
    rejected, never handed to an agent."""
    trace_id = trace_id or str(uuid.uuid4())

    injection_check = check_prompt_injection(request.get("destination_city", ""))
    if injection_check["is_suspicious"]:
        record_event(trace_id, "prompt_injection_blocked", {"request": request, "matched": injection_check["matched_patterns"]})
        raise PromptInjectionDetectedError(
            f"Request blocked by input guardrail: {injection_check['matched_patterns']}"
        )

    initial_state: TripState = {
        "trace_id": trace_id,
        "request": request,
        "status": "ok",
        "errors": [],
    }
    record_event(trace_id, "request_received", {"request": request})
    start_request_trace(trace_id, dict(request))

    final_state = await build_graph().ainvoke(initial_state)

    record_event(trace_id, "request_completed", {"status": final_state.get("status", "ok")})
    end_request_trace(trace_id, output={"status": final_state.get("status", "ok"), "approval": final_state.get("approval")})
    return final_state
