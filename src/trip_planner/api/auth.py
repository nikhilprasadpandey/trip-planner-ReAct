"""Mock OIDC/RBAC adapter (spec §3.7).

Implements the same shape a real OIDC client would (resolve a bearer token
-> an authenticated employee profile) so swapping in a real enterprise IdP
later is a drop-in replacement of `resolve_identity`, not a rewrite of every
caller. Real IdP/SSO is intentionally left out of the live demo per the
spec's build-sequencing guidance; MOCK_AUTH_ENABLED gates this stand-in.

Job level drives two things downstream, per spec: which spend tier/cabin
class applies (Policy Agent / guardrails), and who an approval routes to —
both re-checked at the Policy Agent's retrieval call, not just here.
"""
from __future__ import annotations

import os
from typing import TypedDict

from fastapi import Header, HTTPException


class EmployeeIdentity(TypedDict):
    employee_id: str
    job_level: str   # must match a key in config/guardrails.yaml job_levels


# Two synthetic personas for the demo (spec §6, Pass 3: "two synthetic
# employees at different job levels asking the same question").
_MOCK_PERSONAS: dict[str, EmployeeIdentity] = {
    "employee-ic-001": {"employee_id": "employee-ic-001", "job_level": "ic"},
    "employee-mgr-001": {"employee_id": "employee-mgr-001", "job_level": "manager"},
    "employee-dir-001": {"employee_id": "employee-dir-001", "job_level": "director"},
}


async def resolve_identity(x_employee_id: str = Header(default="employee-ic-001")) -> EmployeeIdentity:
    """FastAPI dependency. Reads the `X-Employee-Id` header and resolves it
    to a job-level-scoped identity.

    Swap for a real OIDC bearer-token verification here when MOCK_AUTH_ENABLED
    is false — the return type (EmployeeIdentity) is the contract the rest of
    the app depends on, so nothing downstream needs to change.
    """
    if os.environ.get("MOCK_AUTH_ENABLED", "true").lower() != "true":
        raise HTTPException(status_code=501, detail="Real OIDC auth is not wired up yet")

    identity = _MOCK_PERSONAS.get(x_employee_id)
    if identity is None:
        raise HTTPException(status_code=401, detail=f"Unknown employee id: {x_employee_id!r}")
    return identity
