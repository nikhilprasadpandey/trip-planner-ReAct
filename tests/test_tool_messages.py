"""Regression coverage for parse_tool_message_content — the real bug: MCP
tool results (via langchain_mcp_adapters + gpt-4.1) arrive as
`ToolMessage.content = [{"type": "text", "text": "<json>"}]`, not a plain
JSON string. The original extraction code only handled str/dict, so every
successful weather/flight tool call was silently treated as "no result"
even though the tool worked — caught live against the real stack, not by
unit tests whose ToolMessage fixtures used plain-string content."""
from __future__ import annotations

from trip_planner.agents.tool_messages import parse_tool_message_content


def test_plain_json_string():
    assert parse_tool_message_content('{"a": 1}') == {"a": 1}


def test_non_json_string_falls_back_to_raw():
    assert parse_tool_message_content("not json") == {"raw": "not json"}


def test_plain_dict_passthrough():
    assert parse_tool_message_content({"a": 1}) == {"a": 1}


def test_list_of_text_blocks_the_real_mcp_shape():
    """This exact shape was silently dropped before the fix."""
    content = [{"type": "text", "text": '{"latitude": 30.2, "longitude": -97.7}', "id": "lc_abc"}]
    assert parse_tool_message_content(content) == {"latitude": 30.2, "longitude": -97.7}


def test_list_of_text_blocks_containing_a_json_array():
    content = [{"type": "text", "text": '[{"section_id": "3a"}, {"section_id": "4"}]'}]
    assert parse_tool_message_content(content) == [{"section_id": "3a"}, {"section_id": "4"}]


def test_list_of_text_blocks_non_json_falls_back_to_raw():
    content = [{"type": "text", "text": "Error executing tool: boom"}]
    assert parse_tool_message_content(content) == {"raw": "Error executing tool: boom"}


def test_empty_list_returns_none():
    assert parse_tool_message_content([]) is None


def test_list_without_text_blocks_passes_through_as_is():
    content = [{"type": "image", "url": "..."}]
    assert parse_tool_message_content(content) == content


def test_raw_python_list_passthrough():
    """A plain (non-MCP) LangChain tool returning a Python list directly,
    not yet stringified into content blocks."""
    assert parse_tool_message_content([{"section_id": "3a"}]) == [{"section_id": "3a"}]


def test_none_content_returns_none():
    assert parse_tool_message_content(None) is None
