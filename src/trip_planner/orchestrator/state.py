"""Shared LangGraph state for the trip-planning orchestrator.

One `trace_id` flows through this state and is the join key across every
agent/tool call, cache hit/miss, guardrail check, audit record, and Langfuse
span (spec: "Every request carries one trace_id...").
"""
from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class TripRequest(TypedDict):
    employee_id: str
    job_level: str              # "ic" | "manager" | "director" — see config/guardrails.yaml
    destination_city: str
    origin_airport: str         # IATA code
    destination_airport: str    # IATA code
    departure_date: str         # ISO date
    cabin_class: NotRequired[str]
    is_international: NotRequired[bool]


class TripState(TypedDict):
    trace_id: str
    request: TripRequest

    geocode: NotRequired[dict]
    weather: NotRequired[dict]
    flight_search: NotRequired[dict]

    policy_evaluation: NotRequired[dict]
    approval: NotRequired[dict]
    reflection_count: NotRequired[int]   # how many times Policy->Flight reflection has looped (spec §3.1)
    cost: NotRequired[dict]              # dual cost ledger snapshot (spec §3.5), attached at request completion

    status: NotRequired[str]            # "ok" | "degraded" | "error"
    errors: NotRequired[list[str]]
    audit_events: NotRequired[list[dict[str, Any]]]
