"""Base for every tool-scoped ReAct agent in the system.

Enforces the spec's "every agent's tool set is explicitly allow-listed at
construction time" rule (§3.1) as actual code, not just convention: building
an agent with a tool outside its declared ALLOWED_TOOLS raises, and it's
checked again at call time (guardrails/allowlist.py adds a second,
independent check at the tool-call boundary — defense in depth, §3.4).
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod

from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent

from trip_planner.config_loader import model_prices_config


class ToolNotAllowedError(Exception):
    """Raised when an agent is built with a tool outside its allow-list."""


class AllowListedReActAgent(ABC):
    """Subclass per domain agent (Weather, Flight, Policy, ...).

    Subclasses set `ALLOWED_TOOLS` (a set of MCP tool names) and `SYSTEM_PROMPT`.
    """

    ALLOWED_TOOLS: frozenset[str] = frozenset()
    SYSTEM_PROMPT: str = "You are a helpful assistant."
    MODEL_ENV_VAR: str = "ORCHESTRATOR_MODEL"  # overridden per subclass if needed

    def __init__(self, tools: list, model_name: str | None = None):
        provided = {t.name for t in tools}
        disallowed = provided - set(self.ALLOWED_TOOLS)
        if disallowed:
            raise ToolNotAllowedError(
                f"{type(self).__name__} was given tools outside its allow-list: {disallowed}"
            )
        self.tools = tools
        self.model_name = model_name or model_prices_config().get("default_model", "claude-sonnet-5")
        self._runnable = create_react_agent(
            ChatAnthropic(model=self.model_name),
            tools=self.tools,
            prompt=self.SYSTEM_PROMPT,
        )

    async def ainvoke(self, user_message: str) -> dict:
        """Run the ReAct loop for one request; returns the final graph state
        (has a `messages` list — the last message is the agent's answer)."""
        return await self._runnable.ainvoke({"messages": [{"role": "user", "content": user_message}]})

    @classmethod
    @abstractmethod
    def mcp_server_name(cls) -> str:
        """Which MCP server (mcp_servers/mcp_client.py registry) this agent's tools come from."""
        raise NotImplementedError
