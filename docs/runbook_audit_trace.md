# Runbook: auditing a trip request

Given a `trace_id`, this is how to pull the full expense-audit record and
cross-check it against Langfuse (spec §7.5 deliverable).

## 1. Get the trace_id

Every response from `POST /trip-requests` includes it:

```json
{ "trace_id": "8f2c1e40-...", "weather": {...}, "flight_search": {...}, ... }
```

The Streamlit UI shows it in the success banner after planning a trip
("Trip planned ... trace_id `...`").

## 2. Pull the audit trail

```bash
curl http://localhost:8000/audit/8f2c1e40-...
```

Expected shape:

```json
{
  "trace_id": "8f2c1e40-...",
  "call_sequence": [
    {"event_type": "request_received", "timestamp": "..."},
    {"event_type": "weather_node_complete", "timestamp": "..."},
    {"event_type": "flight_node_complete", "timestamp": "..."},
    {"event_type": "llm_call_cost", "timestamp": "..."},
    {"event_type": "approval_auto_approved", "timestamp": "..."},
    {"event_type": "business_cost_recorded", "timestamp": "..."},
    {"event_type": "request_completed", "timestamp": "..."}
  ],
  "candidate_fares": [{"carrier": "DL", "price_usd": 389.0, "cabin_class": "economy", ...}],
  "policy_clauses_applied": [],
  "approval_outcome": {"status": "auto_approved", "approved_by": null},
  "final_fare": {"carrier": "DL", "price_usd": 389.0, ...},
  "agent_cost_usd": 0.0031,
  "business_cost_usd": 389.0
}
```

Read this as: *"what did the agent find, what did policy say, who
approved it, and what did it cost — twice over."*

- **`call_sequence`** is the full agent/tool call sequence for this
  request, in order — useful for reconstructing exactly what happened
  without re-running anything.
- **`approval_outcome`** tells you whether the fare was auto-approved,
  is still pending, or was explicitly approved/rejected and by whom
  (`approved_by` is the granting employee's raw id here — the audit
  *events* themselves have employee ids hashed at write time via
  `audit/redact.py`, but the approval record embedded in the event
  payload predates that hashing for the approver field; treat
  `approved_by` as an internal identifier, not for external reporting).
- **`agent_cost_usd`** vs. **`business_cost_usd`**: the FinOps-on-the-AI
  number and the FinOps-on-the-business-process number, side by side.

## 3. Cross-check against Langfuse

If `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` were set when the request
ran, open the Langfuse UI and search for a trace with `id = <trace_id>` —
the orchestrator uses the same id for both systems
(`observability/tracing.py::start_request_trace`). You should see one
trace with nested spans: `agent:weather`, `agent:flight`, `agent:policy`,
and any `guardrail:*` spans (e.g. `guardrail:approval_required`,
`guardrail:policy_reflection_retry`).

If Langfuse credentials were **not** set, there is nothing to cross-check
— `observability/tracing.py` no-ops entirely in that case. This is expected
in local/offline runs; the audit store above is authoritative regardless.

> Note: the exact Langfuse SDK call shapes in `tracing.py` are marked
> unverified against whatever `langfuse` version ends up pinned — if the
> Langfuse UI doesn't show the expected spans, check that first before
> assuming the audit data itself is wrong.

## 4. Common situations

| Symptom | Likely cause | What to check |
|---|---|---|
| `GET /audit/{trace_id}` returns an empty/near-empty trail | Wrong `trace_id`, or the request errored before any node ran (e.g. blocked by the prompt-injection guardrail) | Check the API response/logs for that request for a 400 (prompt-injection block) |
| `candidate_fares` is null | The flight provider was unavailable/quota-exhausted for that request | `flight_search.reason` in the original response explains why |
| `approval_outcome` is missing | The Policy Agent never got a fare to evaluate (`policy_evaluation.skipped: true`) | Same root cause as above — no fare, no policy check |
| `agent_cost_usd` is 0 or missing | All flight/weather calls were served from the route cache (no new LLM calls) | Not a bug — check for `route_cache_hit` events; this is the cache-savings demo working as intended |
| Two employees, same route/date, different `approval_outcome` | Expected — job-level-scoped spend caps (spec §8 acceptance criterion) | Confirm `job_level` differs between the two requests' `request` payloads |
