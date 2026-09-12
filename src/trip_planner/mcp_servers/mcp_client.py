"""Shared MCP client: spawns the MCP servers over stdio and exposes their
tools as LangChain tools, so agents never talk to httpx/providers directly —
only through MCP, per spec §3.2.

Usage:
    client = build_mcp_client()
    tools = await client.get_tools(server_name="free_tools")
"""
from __future__ import annotations

import sys
from functools import lru_cache

from langchain_mcp_adapters.client import MultiServerMCPClient

# Server registry: name -> stdio launch spec. `booking` is kept separate
# and higher-scrutiny per spec §3.7 — the one mutating server.
_SERVERS = {
    "free_tools": {
        "command": sys.executable,
        "args": ["-m", "trip_planner.mcp_servers.free_tools_server"],
        "transport": "stdio",
    },
    "booking": {
        "command": sys.executable,
        "args": ["-m", "trip_planner.mcp_servers.booking_server"],
        "transport": "stdio",
    },
}


@lru_cache(maxsize=1)
def build_mcp_client() -> MultiServerMCPClient:
    """One client, reused across agents/requests — each call to get_tools()
    spawns/talks to the underlying server process as needed."""
    return MultiServerMCPClient(_SERVERS)


async def load_tools(server_name: str, allowed_tool_names: set[str] | None = None) -> list:
    """Load a server's tools as LangChain tools, optionally filtered to an
    allow-list (see agents/base.py — every agent's tool set is allow-listed
    at construction time)."""
    client = build_mcp_client()
    tools = await client.get_tools(server_name=server_name)
    if allowed_tool_names is None:
        return tools
    return [t for t in tools if t.name in allowed_tool_names]
