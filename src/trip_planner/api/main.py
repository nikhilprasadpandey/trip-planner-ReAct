"""FastAPI API gateway — front door for the orchestrator (spec §2).

M1 scope: authN (mock OIDC persona header), rate limiting, health check, and
the one real endpoint: POST /trip-requests, which runs the LangGraph
orchestrator end to end and returns the resulting state (including the
trace_id — the join key for the audit trail and Langfuse, added in M2/M3).
"""
from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from trip_planner.agents.policy_agent import answer_policy_question
from trip_planner.api.auth import EmployeeIdentity, resolve_identity
from trip_planner.api.rate_limit import limiter
from trip_planner.audit.store import get_trip_audit_trail
from trip_planner.guardrails.approval_gate import get_approval, grant_approval, reject_approval
from trip_planner.guardrails.prompt_injection import PromptInjectionDetectedError
from trip_planner.orchestrator.graph import run_trip_planning
from trip_planner.orchestrator.state import TripRequest
from trip_planner.tools.booking_tools import book_flight_stub

app = FastAPI(title="Corporate Travel Planner — API Gateway")
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request, exc):  # pragma: no cover - slowapi wiring
    from starlette.responses import JSONResponse

    return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"})


@app.exception_handler(PromptInjectionDetectedError)
async def _prompt_injection_handler(request, exc):
    from starlette.responses import JSONResponse

    return JSONResponse(status_code=400, content={"detail": str(exc)})


class TripRequestIn(BaseModel):
    destination_city: str
    origin_airport: str
    destination_airport: str
    departure_date: str
    cabin_class: str = "economy"
    is_international: bool = False


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/trip-requests")
@limiter.limit("60/minute")
async def create_trip_request(
    request: Request,  # required first positional arg for slowapi's rate-limit decorator
    body: TripRequestIn,
    identity: EmployeeIdentity = Depends(resolve_identity),
) -> dict:
    trip_request: TripRequest = {
        "employee_id": identity["employee_id"],
        "job_level": identity["job_level"],
        "destination_city": body.destination_city,
        "origin_airport": body.origin_airport.upper(),
        "destination_airport": body.destination_airport.upper(),
        "departure_date": body.departure_date,
        "cabin_class": body.cabin_class,
        "is_international": body.is_international,
    }
    final_state = await run_trip_planning(trip_request)
    return final_state


class ApprovalDecisionIn(BaseModel):
    approved_by: str


@app.post("/approvals/{trace_id}/grant")
async def grant_trip_approval(trace_id: str, body: ApprovalDecisionIn, identity: EmployeeIdentity = Depends(resolve_identity)) -> dict:
    """Demo endpoint: a higher-job-level persona grants a pending approval.
    Real RBAC on *who* may approve *what* is spec'd for a later pass — this
    exists so the approve -> book path is exercisable end to end now."""
    try:
        return grant_approval(trace_id, approved_by=identity["employee_id"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/approvals/{trace_id}/reject")
async def reject_trip_approval(trace_id: str, body: ApprovalDecisionIn, identity: EmployeeIdentity = Depends(resolve_identity)) -> dict:
    try:
        return reject_approval(trace_id, rejected_by=identity["employee_id"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/trip-requests/{trace_id}/book")
async def book_trip(trace_id: str) -> dict:
    """The one write action in the system (spec §3.2b) — blocked unless a
    granted approval record already exists for this trace_id."""
    record = get_approval(trace_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No approval record for trace_id={trace_id!r}")
    return await book_flight_stub(trace_id, record["fare"])


class PolicyQuestionIn(BaseModel):
    query: str


@app.post("/policy-questions")
async def ask_policy_question(body: PolicyQuestionIn, identity: EmployeeIdentity = Depends(resolve_identity)) -> dict:
    """General policy Q&A, semantic-cached (spec §3.9) — demonstrates the
    "two differently-worded questions, same clause, cache hit" behavior."""
    trace_id = str(uuid.uuid4())
    return await answer_policy_question(body.query, job_level=identity["job_level"], trace_id=trace_id)


@app.get("/audit/{trace_id}")
async def get_audit_trail(trace_id: str) -> dict:
    """The runbook endpoint (spec §7.5): given a trace_id, the full
    expense-audit record — fares considered, policy applied, approval
    outcome, both cost numbers, full call sequence."""
    return get_trip_audit_trail(trace_id)
