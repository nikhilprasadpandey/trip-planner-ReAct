"""Embeddings adapter for the policy RAG pipeline — OpenAI
text-embedding-3-small, direct (not Azure) — same OPENAI_API_KEY as the
agent LLM calls (agents/base.py), one provider for both.

Swappable by design (same pattern as the flight provider): if you need to
change providers later, keep this module's function signatures and swap
the implementation.
"""
from __future__ import annotations

import os

DEFAULT_MODEL = "text-embedding-3-small"


class Embedder:
    """Thin wrapper so rag/ingest.py and rag/retriever.py depend on this
    interface, not on the OpenAI SDK directly — makes both testable with a
    fake embedder (see tests/test_retriever.py) with no network/API key
    needed."""

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("EMBEDDING_MODEL", DEFAULT_MODEL)
        self._client = None  # lazy — no API key needed unless actually embedding

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI  # local import: keep this dependency optional at import time

            self._client = OpenAI()  # reads OPENAI_API_KEY from the environment
        return self._client

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._get_client().embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]
