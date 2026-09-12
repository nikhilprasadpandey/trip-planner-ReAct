"""Policy Agent (spec §3.1, §3.3, §3.4): retrieves relevant policy clauses,
evaluates a specific fare against them, and produces a grounded explanation.

The actual "in policy or not" decision is deterministic
(guardrails/thresholds.py, sourced from config/guardrails.yaml) — this
agent's LLM reasoning is for the *citable explanation*, not the ruling
itself, and its explanation is checked for groundedness before being
trusted (spec §3.4 output guardrail: never assert a rule that wasn't
actually retrieved).

The reflection loop (re-query the Flight Agent for a cheaper/lower-cabin
alternative on an out-of-policy fare) is orchestrated in
orchestrator/graph.py, not here — this module answers "is this fare okay,
and why", nothing more.
"""
from __future__ import annotations

import json
from typing import TypedDict

from langchain_core.messages import ToolMessage

from trip_planner.agents.base import AllowListedReActAgent
from trip_planner.guardrails.groundedness import check_groundedness
from trip_planner.guardrails.thresholds import ThresholdEvaluation
from trip_planner.guardrails.thresholds import evaluate_fare as evaluate_fare_thresholds
from trip_planner.rag.retriever import Clause, PolicyRetriever
from trip_planner.tools.policy_tools import make_policy_retrieval_tool


class PolicyEvaluation(TypedDict):
    fare: dict
    threshold: ThresholdEvaluation
    retrieved_clauses: list[Clause]
    explanation: str
    grounded: bool
    cited_section_ids: list[str]


class PolicyAgent(AllowListedReActAgent):
    ALLOWED_TOOLS = frozenset({"retrieve_policy_clauses"})
    SYSTEM_PROMPT = (
        "You are the Policy Agent for a corporate travel planner. Given a "
        "fare and the applicable spend cap, use the retrieve_policy_clauses "
        "tool to look up the relevant clauses, then explain in 2-3 "
        "sentences whether the fare is within policy — always cite the "
        "section_id(s) you retrieved (e.g. 'per §3b'). Never state a cap, "
        "cabin-class rule, or approval routing you did not actually "
        "retrieve via the tool."
    )

    @classmethod
    def mcp_server_name(cls) -> str:
        # Not MCP-backed — see tools/policy_tools.py header for why Qdrant
        # retrieval stays a plain LangChain tool per spec §3.2's MCP scope.
        return "n/a (plain LangChain tool, not MCP — see tools/policy_tools.py)"


async def build_policy_agent(job_level: str, retriever: PolicyRetriever | None = None) -> PolicyAgent:
    tool = make_policy_retrieval_tool(job_level, retriever=retriever)
    return PolicyAgent([tool])


def _extract_retrieved_clauses(messages: list) -> list[Clause]:
    for message in reversed(messages):
        if isinstance(message, ToolMessage) and getattr(message, "name", None) == "retrieve_policy_clauses":
            content = message.content
            if isinstance(content, str):
                try:
                    return json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    return []
            if isinstance(content, list):
                return content
    return []


def _final_answer_text(messages: list) -> str:
    for message in reversed(messages):
        if getattr(message, "type", None) == "ai" and getattr(message, "content", None):
            return message.content if isinstance(message.content, str) else str(message.content)
    return ""


async def evaluate_fare(
    job_level: str,
    fare: dict,
    is_international: bool = False,
    retriever: PolicyRetriever | None = None,
) -> PolicyEvaluation:
    """Full evaluation: deterministic ruling + grounded LLM explanation."""
    threshold = evaluate_fare_thresholds(
        job_level=job_level,
        price_usd=fare["price_usd"],
        cabin_class=fare["cabin_class"],
        is_international=is_international,
    )

    agent = await build_policy_agent(job_level, retriever=retriever)
    result = await agent.ainvoke(
        f"Fare: {fare['carrier']} {fare['cabin_class']} at ${fare['price_usd']:.2f}. "
        f"Is this within the employee's policy? The applicable cap is "
        f"${threshold['cap_usd']:.2f}."
    )
    messages = result["messages"]

    retrieved_clauses = _extract_retrieved_clauses(messages)
    explanation = _final_answer_text(messages)
    retrieved_ids = [c["section_id"] for c in retrieved_clauses]
    groundedness = check_groundedness(explanation, retrieved_ids)

    return PolicyEvaluation(
        fare=fare,
        threshold=threshold,
        retrieved_clauses=retrieved_clauses,
        explanation=explanation,
        grounded=groundedness["is_grounded"],
        cited_section_ids=groundedness["cited_section_ids"],
    )
