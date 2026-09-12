"""Policy clause retrieval, scoped by job level (spec §3.3 — "the single
most convincing demo moment": same clause corpus, filtered results, so a
manager-level query surfaces the manager-tier cap, never the IC tier's).

`PolicyRetriever` takes its index client and embedder as constructor args
so it's testable with fakes (see tests/test_retriever.py) — no live
Qdrant/Azure OpenAI credentials needed to verify the job-level filter is
built and applied correctly. The `IndexClient` Protocol below is an
internal, Pinecone-shaped seam (`query(vector, filter, top_k,
include_metadata) -> {"matches": [...]}`) that `_QdrantIndexAdapter` wraps
the real Qdrant client to match, so swapping the vector DB again later
means writing a new adapter, not touching `retrieve()` or its tests.
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
    """The subset of index behavior this module depends on."""

    def query(self, *, vector: list[float], filter: dict, top_k: int, include_metadata: bool) -> dict: ...


class _QdrantIndexAdapter:
    """Wraps qdrant_client.QdrantClient to present the IndexClient shape
    above. Translates our `{"job_levels": {"$in": [...]}}` filter into a
    Qdrant `Filter(must=[FieldCondition(match=MatchAny(...))])` and reshapes
    Qdrant's response into `{"matches": [{"id", "score", "metadata"}]}`."""

    def __init__(self, client, collection_name: str):
        self._client = client
        self._collection_name = collection_name

    def query(self, *, vector: list[float], filter: dict, top_k: int, include_metadata: bool) -> dict:
        from qdrant_client import models

        job_levels = filter.get("job_levels", {}).get("$in", [])
        qdrant_filter = models.Filter(
            must=[models.FieldCondition(key="job_levels", match=models.MatchAny(any=job_levels))]
        )
        result = self._client.query_points(
            collection_name=self._collection_name,
            query=vector,
            query_filter=qdrant_filter,
            limit=top_k,
            with_payload=include_metadata,
        )
        matches = [
            {"id": str(point.id), "score": point.score, "metadata": point.payload or {}}
            for point in result.points
        ]
        return {"matches": matches}


def _default_index() -> IndexClient:
    from qdrant_client import QdrantClient

    client = QdrantClient(url=os.environ["QDRANT_URL"], api_key=os.environ["QDRANT_API_KEY"])
    collection_name = os.environ.get("QDRANT_COLLECTION_NAME", "corporate-travel-policy")
    return _QdrantIndexAdapter(client, collection_name)


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
        to `job_level`. The filter is applied server-side (a Qdrant payload
        filter), not client-side after the fact — a manager's query can
        never see IC-only clauses score their way into the top-k."""
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
