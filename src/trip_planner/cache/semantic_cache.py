"""Semantic cache for Policy Agent Q&A (spec §3.9): two differently-worded
questions about the same clause should still hit. Job-level-scoped keys — a
cached answer for one tier must never be served to another (a manager's
question can't accidentally return an IC's cap). Invalidated wholesale
whenever the policy corpus changes (rag/ingest.py calls `invalidate_all()`
at the end of a successful ingest).

Cosine similarity over the same embeddings used for retrieval
(rag/embeddings.py) — no new dependency, and "semantically the same
question" and "semantically the same policy clause" are the same notion of
similarity here, so reusing the embedder is deliberate, not just
convenient.

This is a general policy-question cache (agents/policy_agent.py's
`answer_policy_question`) — it does not sit in front of per-fare
evaluation (evaluate_fare), because a fare's price is part of that prompt
and baking a specific price into a "semantically similar" match would risk
serving a stale ruling for a different price. Caching there would look
like it worked while quietly being wrong; this module is deliberately
scoped to where similarity-matching is actually safe.
"""
from __future__ import annotations

import math
from typing import Any

from trip_planner.rag.embeddings import Embedder

# Empirically set against real text-embedding-3-small output (checked live,
# not assumed): paraphrases of the same policy question scored 0.70-0.78
# cosine similarity; genuinely different questions scored 0.35-0.36. 0.70
# sits just under the paraphrase floor, with roughly 2x margin above the
# unrelated-question ceiling — comfortable room either way. An initial guess
# of 0.92 here (never checked against real embeddings) meant the cache
# never hit in practice; re-tune again if the corpus/model changes.
_DEFAULT_SIMILARITY_THRESHOLD = 0.70


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticPolicyCache:
    def __init__(self, embedder: Embedder | None = None, similarity_threshold: float = _DEFAULT_SIMILARITY_THRESHOLD):
        self._embedder = embedder or Embedder()
        self._threshold = similarity_threshold
        self._entries: dict[str, list[tuple[list[float], str, Any]]] = {}

    def get(self, query: str, job_level: str) -> Any | None:
        candidates = self._entries.get(job_level, [])
        if not candidates:
            return None
        query_vector = self._embedder.embed_query(query)
        best_result, best_score = None, 0.0
        for vector, _text, result in candidates:
            score = _cosine_similarity(query_vector, vector)
            if score > best_score:
                best_score, best_result = score, result
        return best_result if best_score >= self._threshold else None

    def set(self, query: str, job_level: str, result: Any) -> None:
        vector = self._embedder.embed_query(query)
        self._entries.setdefault(job_level, []).append((vector, query, result))

    def invalidate_all(self) -> None:
        """Call after re-ingesting the policy corpus — every cached answer
        may now be stale."""
        self._entries.clear()


_DEFAULT_CACHE = SemanticPolicyCache()


def get_default_cache() -> SemanticPolicyCache:
    return _DEFAULT_CACHE
