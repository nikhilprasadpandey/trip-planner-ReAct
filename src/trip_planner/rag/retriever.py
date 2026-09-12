"""Policy clause retrieval, scoped by job level (spec §3.3 — "the single
most convincing demo moment": same clause corpus, filtered results, so a
manager-level query surfaces the manager-tier cap, never the IC tier's).

`PolicyRetriever` takes its Pinecone index and embedder as constructor args
so it's testable with fakes (see tests/test_retriever.py) — no live
Pinecone/OpenAI credentials needed to verify the job-level filter is built
and applied correctly.
"""
from __future__ import annotations

import os
from typing import Protocol, TypedDict

from trip_planner.rag.embeddings import Embedder


class Clause(TypedDict):
    section_id: str
    title: str
    text: str
    job_levels: list[str]
    score: float


class IndexClient(Protocol):
    """The subset of the Pinecone Index interface this module depends on."""

    def query(self, *, vector: list[float], filter: dict, top_k: int, include_metadata: bool) -> dict: ...


def _default_index() -> IndexClient:
    from pinecone import Pinecone

    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    index_name = os.environ.get("PINECONE_INDEX_NAME", "corporate-travel-policy")
    return pc.Index(index_name)


class PolicyRetriever:
    def __init__(self, index: IndexClient | None = None, embedder: Embedder | None = None):
        self._index = index  # resolved lazily via _get_index() so no credentials are needed until first use
        self._embedder = embedder or Embedder()

    def _get_index(self) -> IndexClient:
        if self._index is None:
            self._index = _default_index()
        return self._index

    def retrieve(self, query: str, job_level: str, top_k: int = 4) -> list[Clause]:
        """Top-k clauses relevant to `query`, filtered to sections applicable
        to `job_level`. The filter is applied server-side (Pinecone metadata
        filter), not client-side after the fact — a manager's query can never
        see IC-only clauses score their way into the top-k."""
        vector = self._embedder.embed_query(query)
        result = self._get_index().query(
            vector=vector,
            filter={"job_levels": {"$in": [job_level]}},
            top_k=top_k,
            include_metadata=True,
        )

        clauses: list[Clause] = []
        for match in result.get("matches", []):
            metadata = match.get("metadata", {})
            clauses.append(
                Clause(
                    section_id=metadata.get("section_id", match.get("id", "")),
                    title=metadata.get("title", ""),
                    text=metadata.get("text", ""),
                    job_levels=metadata.get("job_levels", []),
                    score=match.get("score", 0.0),
                )
            )
        return clauses
