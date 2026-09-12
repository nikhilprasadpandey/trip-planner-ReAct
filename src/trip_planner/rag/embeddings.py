"""Embeddings adapter for the policy RAG pipeline — Azure OpenAI
(text-embedding-3-small deployment). This is the one non-Anthropic API call
in the system; every agent's reasoning stays on Claude (see cost/ledger.py,
which tracks this separately from LLM token cost — see
config/model_prices.yaml `embeddings:`).

Swappable by design (same pattern as the flight provider): if you need to
change providers later, keep this module's function signatures and swap
the implementation.
"""
from __future__ import annotations

import os


class Embedder:
    """Thin wrapper so rag/ingest.py and rag/retriever.py depend on this
    interface, not on the Azure OpenAI SDK directly — makes both testable
    with a fake embedder (see tests/test_retriever.py) with no network/API
    key needed."""

    def __init__(self, deployment: str | None = None):
        self.deployment = deployment or os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
        self._client = None  # lazy — no credentials needed unless actually embedding

    def _get_client(self):
        if self._client is None:
            from openai import AzureOpenAI  # local import: keep this dependency optional at import time

            self._client = AzureOpenAI(
                api_key=os.environ["AZURE_OPENAI_API_KEY"],
                azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            )
        return self._client

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._get_client().embeddings.create(model=self.deployment, input=texts)
        return [item.embedding for item in response.data]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]
