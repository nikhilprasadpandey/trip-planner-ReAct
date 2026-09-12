"""Semantic cache for policy Q&A (spec §3.9): differently-worded questions
about the same clause should hit; job-level scoping must never leak one
tier's cached answer to another; invalidate_all() clears everything."""
from __future__ import annotations

from trip_planner.cache.semantic_cache import SemanticPolicyCache


class FakeEmbedder:
    """Maps fixed phrases to hand-picked vectors so similarity is
    deterministic and testable without a real embedding model."""

    _VECTORS = {
        "what is my spend cap": [1.0, 0.0],
        "what's my spending limit": [0.99, 0.05],   # near-identical meaning -> should hit
        "what carriers are preferred": [0.0, 1.0],   # unrelated -> should miss
    }

    def embed_query(self, text: str) -> list[float]:
        return self._VECTORS.get(text, [0.5, 0.5])


def test_differently_worded_question_still_hits():
    cache = SemanticPolicyCache(embedder=FakeEmbedder(), similarity_threshold=0.95)
    cache.set("what is my spend cap", "ic", {"answer": "It's $600."})

    result = cache.get("what's my spending limit", "ic")
    assert result == {"answer": "It's $600."}


def test_unrelated_question_misses():
    cache = SemanticPolicyCache(embedder=FakeEmbedder(), similarity_threshold=0.95)
    cache.set("what is my spend cap", "ic", {"answer": "It's $600."})

    assert cache.get("what carriers are preferred", "ic") is None


def test_job_level_scoping_never_leaks_across_tiers():
    cache = SemanticPolicyCache(embedder=FakeEmbedder(), similarity_threshold=0.95)
    cache.set("what is my spend cap", "ic", {"answer": "IC cap is $600."})

    # Same/near-identical question, different job level — must not hit the IC entry.
    assert cache.get("what's my spending limit", "manager") is None


def test_invalidate_all_clears_every_entry():
    cache = SemanticPolicyCache(embedder=FakeEmbedder(), similarity_threshold=0.95)
    cache.set("what is my spend cap", "ic", {"answer": "It's $600."})
    cache.invalidate_all()

    assert cache.get("what is my spend cap", "ic") is None
