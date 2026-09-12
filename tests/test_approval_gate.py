"""The core guardrail (spec §3.4/§8): book_flight is never called without an
approval record for that trace_id."""
from __future__ import annotations

import pytest

from trip_planner.guardrails import approval_gate


@pytest.fixture(autouse=True)
def _clear_approval_records():
    approval_gate._clear_all()
    yield
    approval_gate._clear_all()


def test_booking_blocked_with_no_approval_record():
    with pytest.raises(approval_gate.ApprovalRequiredError):
        approval_gate.require_approval_for_booking("trace-no-record")


def test_booking_allowed_after_auto_approve():
    approval_gate.auto_approve("trace-1", job_level="ic", fare={"price_usd": 400})
    record = approval_gate.require_approval_for_booking("trace-1")
    assert record["status"] == "auto_approved"


def test_booking_blocked_while_pending_then_allowed_after_grant():
    approval_gate.create_pending_approval("trace-2", job_level="ic", fare={"price_usd": 900}, approver_role="manager")

    with pytest.raises(approval_gate.ApprovalRequiredError):
        approval_gate.require_approval_for_booking("trace-2")

    approval_gate.grant_approval("trace-2", approved_by="mgr-001")
    record = approval_gate.require_approval_for_booking("trace-2")
    assert record["status"] == "approved"
    assert record["approved_by"] == "mgr-001"


def test_rejected_approval_still_blocks_booking():
    approval_gate.create_pending_approval("trace-3", job_level="ic", fare={"price_usd": 900}, approver_role="manager")
    approval_gate.reject_approval("trace-3", rejected_by="mgr-001")

    with pytest.raises(approval_gate.ApprovalRequiredError):
        approval_gate.require_approval_for_booking("trace-3")
