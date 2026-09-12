"""Tool-call guardrail (spec §3.4): per-agent allow-list enforcement,
defense in depth on top of agents/base.py's construction-time check.

agents/base.py already refuses to *build* an agent with a disallowed tool —
that's the primary control. This module wraps each tool so the check is
re-verified at the moment of *invocation* too, and every call is logged
with the trace_id, so a future bug that mutates an agent's tool list after
construction (or a new agent that forgets to subclass the base) still can't
silently call something outside its allow-list.
"""
from __future__ import annotations

from trip_planner.audit.store import record_event


class ToolNotAllowedError(Exception):
    pass


def guard_tools(tools: list, agent_name: str, allowed_tool_names: frozenset[str], trace_id: str) -> list:
    """Wrap each tool's coroutine/func so every call is checked against the
    allow-list and logged. Returns new tool objects; does not mutate the
    originals."""
    guarded = []
    for tool in tools:
        if tool.name not in allowed_tool_names:
            raise ToolNotAllowedError(f"{agent_name} attempted to use disallowed tool {tool.name!r}")
        guarded.append(_wrap(tool, agent_name, trace_id))
    return guarded


def _wrap(tool, agent_name: str, trace_id: str):
    original_coroutine = getattr(tool, "coroutine", None)
    original_func = getattr(tool, "func", None)

    def _log(tool_args: dict) -> None:
        record_event(trace_id, "tool_call_allowed", {"agent": agent_name, "tool": tool.name, "args": tool_args})

    if original_coroutine is not None:
        async def _guarded_coroutine(*args, **kwargs):
            _log(kwargs or {"args": args})
            return await original_coroutine(*args, **kwargs)

        tool.coroutine = _guarded_coroutine

    if original_func is not None:
        def _guarded_func(*args, **kwargs):
            _log(kwargs or {"args": args})
            return original_func(*args, **kwargs)

        tool.func = _guarded_func

    return tool
