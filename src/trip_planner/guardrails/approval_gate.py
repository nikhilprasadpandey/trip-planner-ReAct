"""The core guardrail for this use case (spec §3.4): `book_flight` is never
called without an approval record for that trace_id. Any fare exceeding the
applicable policy threshold blocks booking and instead emits an approval
request; the agent must not call the mutating tool until a record exists.

Storage here is an in-memory dict, deliberately simple for M2 — every write
is also mirrored to the JSONL audit sink so the trail survives a process
restart in spirit (not durably; M3's audit/store.py replaces this dict with
a real, queryable, append-only table and this module's functions get a
thin swap to read/write through it instead — the *interface* below is what
mcp_servers/booking_server.py and orchestrator/graph.py depend on, so that
swap doesn't ripple outward).
"""
from __future__ import annotations

from typing import Literal, TypedDict

from trip_planner.audit.jsonl_sink import record_event

ApprovalStatus = Literal["auto_approved", "pending", "approved", "rejected"]


class ApprovalRecord(TypedDict):
    trace_id: str
    status: ApprovalStatus
    approver_role: str
    approved_by: str | None
    fare: dict
    job_level: str


class ApprovalRequiredError(Exception):
    """Raised by require_approval_for_booking when no granted record exists."""


_RECORDS: dict[str, ApprovalRecord] = {}


def auto_approve(trace_id: str, job_level: str, fare: dict) -> ApprovalRecord:
    record = ApprovalRecord(
        trace_id=trace_id, status="auto_approved", approver_role="", approved_by=None,
        fare=fare, job_level=job_level,
    )
    _RECORDS[trace_id] = record
    record_event(trace_id, "approval_auto_approved", dict(record))
    return record


def create_pending_approval(trace_id: str, job_level: str, fare: dict, approver_role: str) -> ApprovalRecord:
    record = ApprovalRecord(
        trace_id=trace_id, status="pending", approver_role=approver_role, approved_by=None,
        fare=fare, job_level=job_level,
    )
    _RECORDS[trace_id] = record
    record_event(trace_id, "approval_required", dict(record))
    return record


def grant_approval(trace_id: str, approved_by: str) -> ApprovalRecord:
    record = _RECORDS.get(trace_id)
    if record is None:
        raise KeyError(f"No approval request exists for trace_id={trace_id!r}")
    record["status"] = "approved"
    record["approved_by"] = approved_by
    record_event(trace_id, "approval_granted", dict(record))
    return record


def reject_approval(trace_id: str, rejected_by: str) -> ApprovalRecord:
    record = _RECORDS.get(trace_id)
    if record is None:
        raise KeyError(f"No approval request exists for trace_id={trace_id!r}")
    record["status"] = "rejected"
    record["approved_by"] = rejected_by
    record_event(trace_id, "approval_rejected", dict(record))
    return record


def get_approval(trace_id: str) -> ApprovalRecord | None:
    return _RECORDS.get(trace_id)


def require_approval_for_booking(trace_id: str) -> ApprovalRecord:
    """The gate itself. Called by booking_server.py's book_flight tool
    (and by anything else that might attempt to call it) before doing
    anything else. Raises unless a granted/auto-approved record exists —
    this is the invariant spec §8's acceptance criteria and
    tests/test_approval_gate.py check."""
    record = _RECORDS.get(trace_id)
    if record is None or record["status"] not in ("auto_approved", "approved"):
        record_event(trace_id, "booking_blocked_no_approval", {"trace_id": trace_id})
        raise ApprovalRequiredError(
            f"book_flight blocked for trace_id={trace_id!r}: no granted approval record"
        )
    return record


def _clear_all() -> None:
    """Test helper only."""
    _RECORDS.clear()
