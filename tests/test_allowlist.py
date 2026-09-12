"""Defense-in-depth tool-call guardrail (spec §3.4) — re-verified at
invocation time, on top of agents/base.py's construction-time check."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from trip_planner.guardrails.allowlist import ToolNotAllowedError, guard_tools


class _FakeTool:
    def __init__(self, name):
        self.name = name
        self.func = None

        async def _coro(**kwargs):
            return f"{name} called with {kwargs}"

        self.coroutine = _coro


async def test_allowed_tool_call_is_logged_and_passes_through():
    tool = _FakeTool("search_flights")
    guarded = guard_tools([tool], agent_name="FlightAgent", allowed_tool_names=frozenset({"search_flights"}), trace_id="t1")

    result = await guarded[0].coroutine(origin="SFO")
    assert "search_flights" in result


def test_disallowed_tool_raises_at_guard_time():
    tool = _FakeTool("book_flight")
    with pytest.raises(ToolNotAllowedError):
        guard_tools([tool], agent_name="FlightAgent", allowed_tool_names=frozenset({"search_flights"}), trace_id="t1")
