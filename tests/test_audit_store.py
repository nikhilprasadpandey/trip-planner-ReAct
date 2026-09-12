"""SQLAlchemy audit store (spec §3.6, §8): append-only, queryable by
trace_id, PII redacted before write."""
from __future__ import annotations

from trip_planner.audit import store


def test_record_and_read_back_events_in_order():
    store.record_event("trace-1", "request_received", {"request": {"destination_city": "Austin"}})
    store.record_event("trace-1", "flight_node_complete", {"result": {"flight_search": {"available": True}}})

    events = store.get_events("trace-1")
    assert [e["event_type"] for e in events] == ["request_received", "flight_node_complete"]


def test_employee_id_redacted_at_write_time():
    store.record_event("trace-2", "request_received", {"request": {"employee_id": "employee-ic-001"}})
    events = store.get_events("trace-2")
    assert events[0]["payload"]["request"]["employee_id"] != "employee-ic-001"


def test_events_scoped_by_trace_id():
    store.record_event("trace-a", "request_received", {"x": 1})
    store.record_event("trace-b", "request_received", {"x": 2})

    assert len(store.get_events("trace-a")) == 1
    assert len(store.get_events("trace-b")) == 1


def test_get_trip_audit_trail_aggregates_the_expense_audit_shape():
    trace_id = "trace-3"
    fare = {"carrier": "DL", "price_usd": 389.0, "cabin_class": "economy"}

    store.record_event(trace_id, "request_received", {"request": {"employee_id": "employee-ic-001"}})
    store.record_event(trace_id, "flight_node_complete", {"result": {"flight_search": {"fares": [fare]}}})
    store.record_event(trace_id, "approval_auto_approved", {"status": "auto_approved", "approved_by": None, "fare": fare})
    store.record_event(trace_id, "llm_call_cost", {"agent": "FlightAgent", "model": "claude-sonnet-5", "cost_usd": 0.002})
    store.record_event(trace_id, "business_cost_recorded", {"fare_price_usd": 389.0})

    trail = store.get_trip_audit_trail(trace_id)

    assert trail["candidate_fares"] == [fare]
    assert trail["approval_outcome"] == {"status": "auto_approved", "approved_by": None}
    assert trail["final_fare"] == fare
    assert trail["business_cost_usd"] == 389.0
    assert trail["agent_cost_usd"] == 0.002
    assert [c["event_type"] for c in trail["call_sequence"]] == [
        "request_received", "flight_node_complete", "approval_auto_approved", "llm_call_cost", "business_cost_recorded",
    ]
