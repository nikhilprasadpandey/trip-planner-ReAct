"""Planning step (spec §3.1): decides step order respecting dependencies —
can't check weather before geocoding, can't check policy before a fare
exists. The dependency order below is fixed; the conditional part of the
plan — Policy Agent looping back to Flight Agent on an out-of-policy fare,
up to `max_reflection_retries` — is the reflection edge in
orchestrator/graph.py, not a re-plan of this list.
"""
from __future__ import annotations

# Each step name maps to a node in orchestrator/graph.py.
CORE_FLOW: list[str] = ["geocode", "weather", "flight_search", "policy_check"]


def plan_steps() -> list[str]:
    return list(CORE_FLOW)
