"""Shared helper for pulling structured data back out of a ReAct agent's
`ToolMessage.content`.

`ToolMessage.content` is not reliably a plain JSON string. Depending on the
tool source (MCP vs. a plain LangChain tool) and SDK version, it may be:
  - a JSON string (`'{"latitude": ...}'`)
  - a list of content blocks (`[{"type": "text", "text": "<json string>"}]`)
    — this is what the real MCP + langchain_openai stack actually produces,
    and was the cause of a real bug: orchestrator/graph.py's extraction only
    handled the str/dict shapes, so every successful weather/flight tool
    call was silently treated as "no result" even though the tool worked —
    caught live, not by the original unit tests, which constructed
    ToolMessage fixtures with plain-string content that doesn't match what
    the real stack produces.
  - a plain dict/list (a tool's raw Python return value, not yet stringified)

`parse_tool_message_content` normalizes all three.
"""
from __future__ import annotations

import json
from typing import Any


def parse_tool_message_content(content: Any) -> Any | None:
    if isinstance(content, str):
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return {"raw": content}

    if isinstance(content, list):
        if not content:
            return None
        text_parts = [
            block.get("text") for block in content
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
        ]
        if text_parts:
            joined = "".join(text_parts)
            try:
                return json.loads(joined)
            except (json.JSONDecodeError, TypeError):
                return {"raw": joined}
        # Not content-block-shaped (no "text" blocks) — a plain LangChain
        # tool's raw Python list return, or a non-text content block type.
        # Either way, hand it back as-is rather than discarding it.
        return content

    if isinstance(content, dict):
        return content

    return None
