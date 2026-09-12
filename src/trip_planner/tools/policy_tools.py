"""Policy retrieval tool — exposed only to the Policy Agent (spec §3.3).

The `job_level` is baked into the tool at construction time from the
employee's *authenticated* identity, not exposed as an LLM-fillable
parameter. This is deliberate: it's the "re-checked at the Policy Agent's
retrieval call, not just at the API gateway" requirement (spec §3.7) — an
employee can't get the LLM to ask for another tier's clauses by phrasing the
question differently, because the tool itself can't take job_level as input.

Not an MCP tool: spec §3.2 scopes the two MCP servers to flight-pricing and
booking; Pinecone retrieval is a plain LangChain tool.
"""
from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from trip_planner.rag.retriever import Clause, PolicyRetriever


class _PolicyQueryInput(BaseModel):
    query: str = Field(description="What to look up in the corporate travel policy, e.g. 'spend cap for a domestic flight'.")


def make_policy_retrieval_tool(job_level: str, retriever: PolicyRetriever | None = None) -> StructuredTool:
    retriever = retriever or PolicyRetriever()

    async def _retrieve_policy_clauses(query: str) -> list[Clause]:
        return retriever.retrieve(query, job_level=job_level, top_k=4)

    return StructuredTool.from_function(
        coroutine=_retrieve_policy_clauses,
        name="retrieve_policy_clauses",
        description=(
            "Retrieve the most relevant corporate travel policy clauses for the "
            "current employee's job level. Always cite the returned section_id "
            "when asserting a policy rule — never state a cap, cabin-class rule, "
            "or approval routing that wasn't actually returned by this tool."
        ),
        args_schema=_PolicyQueryInput,
    )
