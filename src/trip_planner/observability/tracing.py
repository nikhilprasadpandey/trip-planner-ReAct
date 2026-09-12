"""One Langfuse trace per trip-planning request, nested spans per
agent/tool call, guardrail events as span-level metadata (spec §3.8).

Every function here is best-effort and never raises — tracing must not be
able to break the orchestrator if Langfuse is unreachable or its SDK shape
has moved since this was written. Verify the exact trace()/span() call
shape against whichever `langfuse` version is pinned in pyproject.toml
before relying on this for real observability; the defensive try/except
wrapping is deliberate because that shape isn't pinned down here.

Keyed by trace_id — the same id used in the audit store (audit/store.py)
and returned to the API caller, so a single id reconstructs the full story
across both systems (spec §8 acceptance criteria).
"""
from __future__ import annotations

from trip_planner.observability.langfuse_client import get_client

_ACTIVE_TRACES: dict[str, object] = {}


def start_request_trace(trace_id: str, request: dict) -> None:
    client = get_client()
    if client is None:
        return
    try:
        trace = client.trace(id=trace_id, name="trip_planning_request", metadata={"request": request})
        _ACTIVE_TRACES[trace_id] = trace
    except Exception as exc:  # pragma: no cover - defensive only
        print(f"[observability] failed to start trace {trace_id}: {exc}")


def log_span(trace_id: str, name: str, input: dict | None = None, output: dict | None = None, metadata: dict | None = None) -> None:
    client = get_client()
    if client is None:
        return
    try:
        trace = _ACTIVE_TRACES.get(trace_id)
        if trace is not None:
            trace.span(name=name, input=input, output=output, metadata=metadata)
        else:
            client.trace(id=trace_id).span(name=name, input=input, output=output, metadata=metadata)
    except Exception as exc:  # pragma: no cover - defensive only
        print(f"[observability] failed to log span {name} for {trace_id}: {exc}")


def log_guardrail_event(trace_id: str, event_name: str, metadata: dict) -> None:
    """Guardrail events (approval required/granted, groundedness failed) as
    span-level metadata — makes 'how often do fares come back out-of-policy'
    a queryable Langfuse trend, per spec §3.8."""
    log_span(trace_id, f"guardrail:{event_name}", metadata=metadata)


def end_request_trace(trace_id: str, output: dict | None = None) -> None:
    client = get_client()
    if client is None:
        return
    try:
        trace = _ACTIVE_TRACES.pop(trace_id, None)
        if trace is not None:
            trace.update(output=output)
    except Exception as exc:  # pragma: no cover - defensive only
        print(f"[observability] failed to end trace {trace_id}: {exc}")
