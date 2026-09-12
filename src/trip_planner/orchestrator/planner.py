"""Planning step (spec §3.1): decides step order respecting dependencies —
can't check weather before geocoding, can't check policy before a fare
exists. M1 ships the fixed dependency order below (still "planning", just
not yet conditional); M2 extends this when the Policy Agent's reflection
loop needs to re-plan (loop back to flight search on an out-of-policy fare).
"""
from __future__ import annotations

# Fixed for M1. Each step name maps to a node in orchestrator/graph.py.
CORE_FLOW: list[str] = ["geocode", "weather", "flight_search"]


def plan_steps() -> list[str]:
    return list(CORE_FLOW)
