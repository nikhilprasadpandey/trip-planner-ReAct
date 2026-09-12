"""Offline test for job-level-scoped Qdrant retrieval (spec §3.3) — a
fake index/embedder, no live credentials needed. Verifies the job-level
metadata filter is actually built and passed through to the query."""
from __future__ import annotations

from trip_planner.rag.retriever import PolicyRetriever


class FakeEmbedder:
    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class FakeIndex:
    def __init__(self):
        self.last_query_kwargs: dict | None = None

    def query(self, *, vector, filter, top_k, include_metadata):
        self.last_query_kwargs = {"vector": vector, "filter": filter, "top_k": top_k}
        job_levels = filter["job_levels"]["$in"]
        # Simulate Qdrant's server-side filter: only "return" matches whose
        # metadata job_levels includes the requested tier.
        all_matches = [
            {"id": "3a", "score": 0.9, "metadata": {"section_id": "3a", "title": "IC caps", "text": "$600 cap", "job_levels": ["ic"]}},
            {"id": "3b", "score": 0.85, "metadata": {"section_id": "3b", "title": "Manager caps", "text": "$1200 cap", "job_levels": ["manager"]}},
            {"id": "4", "score": 0.8, "metadata": {"section_id": "4", "title": "Carriers", "text": "prefer AA/DL/UA", "job_levels": ["ic", "manager", "director"]}},
        ]
        filtered = [m for m in all_matches if any(lvl in job_levels for lvl in m["metadata"]["job_levels"])]
        return {"matches": filtered[:top_k]}


def test_ic_query_never_sees_manager_only_clause():
    retriever = PolicyRetriever(index=FakeIndex(), embedder=FakeEmbedder())
    clauses = retriever.retrieve("what is my spend cap", job_level="ic", top_k=4)

    section_ids = {c["section_id"] for c in clauses}
    assert "3a" in section_ids       # IC's own clause
    assert "3b" not in section_ids   # never the manager tier's clause
    assert "4" in section_ids        # shared clause, visible to all tiers


def test_manager_query_gets_manager_clause_not_ic_clause():
    retriever = PolicyRetriever(index=FakeIndex(), embedder=FakeEmbedder())
    clauses = retriever.retrieve("what is my spend cap", job_level="manager", top_k=4)

    section_ids = {c["section_id"] for c in clauses}
    assert "3b" in section_ids
    assert "3a" not in section_ids


def test_filter_is_applied_server_side_not_client_side():
    index = FakeIndex()
    retriever = PolicyRetriever(index=index, embedder=FakeEmbedder())
    retriever.retrieve("caps", job_level="director", top_k=2)

    assert index.last_query_kwargs["filter"] == {"job_levels": {"$in": ["director"]}}
    assert index.last_query_kwargs["top_k"] == 2
