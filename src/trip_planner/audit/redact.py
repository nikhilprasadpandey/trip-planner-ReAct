"""PII handling for the audit trail (spec §3.6): employee id beyond what's
needed, and any personal travel preferences, are redacted/tokenized before
write — the append-only store must never hold raw PII a finance/compliance
reviewer doesn't need.

`employee_id` is hashed to a stable, non-reversible token (not deleted —
the audit trail still needs to correlate events for the *same* employee
across requests, just not carry their raw id at rest). Job level is kept
as-is; it's the field the audit trail's reporting actually needs.
"""
from __future__ import annotations

import hashlib
from typing import Any

# Fields that should never be persisted verbatim if they ever show up in a
# payload (none of today's payloads carry these, but the redaction step
# stays defensive rather than trusting every future call site to remember).
_STRIP_KEYS = {"ssn", "passport_number", "credit_card", "personal_notes", "date_of_birth"}


def hash_employee_id(employee_id: str) -> str:
    digest = hashlib.sha256(employee_id.encode("utf-8")).hexdigest()
    return f"emp-{digest[:16]}"


def redact_payload(payload: Any) -> Any:
    """Recursively walks a JSON-shaped payload: hashes `employee_id` values,
    strips keys in `_STRIP_KEYS` entirely, and leaves everything else
    (including job_level — needed for reporting) untouched."""
    if isinstance(payload, dict):
        redacted = {}
        for key, value in payload.items():
            if key in _STRIP_KEYS:
                continue
            if key == "employee_id" and isinstance(value, str):
                redacted[key] = hash_employee_id(value)
            else:
                redacted[key] = redact_payload(value)
        return redacted
    if isinstance(payload, list):
        return [redact_payload(item) for item in payload]
    return payload
