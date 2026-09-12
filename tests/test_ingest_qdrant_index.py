"""Regression: Qdrant requires a payload index to filter by a field —
without it, every job-level-scoped policy query 400s with "Index required
but not found" (caught live against the real Qdrant Cloud instance, not by
the original test suite, which only exercised the retriever against a
fake index). `_qdrant_collection` must create that index, and must do so
even for a collection that already existed before the index was added."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from trip_planner.rag import ingest


class _FakeCollections:
    def __init__(self, existing_names):
        self.collections = [SimpleNamespace(name=n) for n in existing_names]


class _FakeQdrantClient:
    def __init__(self, existing_collections=(), index_already_exists=False):
        self.created_collections = []
        self.created_indexes = []
        self._existing = list(existing_collections)
        self._index_already_exists = index_already_exists

    def __call__(self, *args, **kwargs):  # acts as the QdrantClient() constructor
        return self

    def get_collections(self):
        return _FakeCollections(self._existing)

    def create_collection(self, collection_name, vectors_config):
        self.created_collections.append(collection_name)

    def create_payload_index(self, collection_name, field_name, field_schema):
        if self._index_already_exists:
            from qdrant_client.http.exceptions import UnexpectedResponse

            raise UnexpectedResponse(status_code=409, reason_phrase="Conflict", content=b"already exists", headers={})
        self.created_indexes.append((collection_name, field_name))


def test_creates_payload_index_on_a_brand_new_collection(monkeypatch):
    fake = _FakeQdrantClient(existing_collections=[])
    monkeypatch.setenv("QDRANT_URL", "http://fake")
    monkeypatch.setenv("QDRANT_API_KEY", "fake")
    monkeypatch.setattr("qdrant_client.QdrantClient", fake)

    ingest._qdrant_collection("corporate-travel-policy")

    assert fake.created_collections == ["corporate-travel-policy"]
    assert fake.created_indexes == [("corporate-travel-policy", "job_levels")]


def test_creates_payload_index_on_a_pre_existing_collection_missing_it(monkeypatch):
    """The bug caught live: a collection created before the index fix
    existed skips create_collection (already exists) but must still get
    the index."""
    fake = _FakeQdrantClient(existing_collections=["corporate-travel-policy"])
    monkeypatch.setenv("QDRANT_URL", "http://fake")
    monkeypatch.setenv("QDRANT_API_KEY", "fake")
    monkeypatch.setattr("qdrant_client.QdrantClient", fake)

    ingest._qdrant_collection("corporate-travel-policy")

    assert fake.created_collections == []
    assert fake.created_indexes == [("corporate-travel-policy", "job_levels")]


def test_idempotent_when_index_already_exists(monkeypatch):
    fake = _FakeQdrantClient(existing_collections=["corporate-travel-policy"], index_already_exists=True)
    monkeypatch.setenv("QDRANT_URL", "http://fake")
    monkeypatch.setenv("QDRANT_API_KEY", "fake")
    monkeypatch.setattr("qdrant_client.QdrantClient", fake)

    ingest._qdrant_collection("corporate-travel-policy")  # must not raise
