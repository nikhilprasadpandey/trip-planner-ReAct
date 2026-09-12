"""FastAPI API gateway — front door for the orchestrator (spec §2).

M1 scope: authN (mock OIDC persona header), rate limiting, health check, and
the one real endpoint: POST /trip-requests, which runs the LangGraph
orchestrator end to end and returns the resulting state (including the
trace_id — the join key for the audit trail and Langfuse, added in M2/M3).
"""
from __future__ import annotations

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from trip_planner.api.auth import EmployeeIdentity, resolve_identity
from trip_planner.api.rate_limit import limiter
from trip_planner.orchestrator.graph import PromptInjectionDetectedError, run_trip_planning
from trip_planner.orchestrator.state import TripRequest

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
    request,  # required first positional arg for slowapi's rate-limit decorator
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
