from __future__ import annotations

from trip_planner.audit.redact import hash_employee_id, redact_payload


def test_employee_id_is_hashed_not_dropped():
    payload = {"employee_id": "employee-ic-001", "job_level": "ic"}
    redacted = redact_payload(payload)

    assert redacted["employee_id"] != "employee-ic-001"
    assert redacted["employee_id"] == hash_employee_id("employee-ic-001")
    assert redacted["job_level"] == "ic"  # not PII, kept for reporting


def test_hash_is_deterministic():
    assert hash_employee_id("employee-ic-001") == hash_employee_id("employee-ic-001")
    assert hash_employee_id("employee-ic-001") != hash_employee_id("employee-mgr-001")


def test_stripped_keys_removed_entirely():
    payload = {"ssn": "123-45-6789", "note": "fine"}
    redacted = redact_payload(payload)
    assert "ssn" not in redacted
    assert redacted["note"] == "fine"


def test_recurses_into_nested_structures():
    payload = {"request": {"employee_id": "employee-ic-001"}, "fares": [{"carrier": "AA"}]}
    redacted = redact_payload(payload)
    assert redacted["request"]["employee_id"] == hash_employee_id("employee-ic-001")
    assert redacted["fares"] == [{"carrier": "AA"}]
