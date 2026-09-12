"""Ingestion pipeline for the corporate travel policy corpus (spec §3.3):
chunk by policy section, embed, upsert to Qdrant with metadata (section
id, job-level applicability, last-updated date).

Run: python -m trip_planner.rag.ingest
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from trip_planner.config_loader import REPO_ROOT
from trip_planner.rag.embeddings import Embedder

CORPUS_PATH = Path(__file__).parent / "corpus" / "policy_source.md"

_LAST_UPDATED_RE = re.compile(r"<!--\s*last_updated:\s*([\d-]+)\s*-->")
_SECTION_HEADING_RE = re.compile(r"^##\s+§(\S+)\s+(.+)$")
_JOB_LEVELS_RE = re.compile(r"<!--\s*job_levels:\s*([a-z,\s]+)\s*-->")


class PolicySection(TypedDict):
    section_id: str
    title: str
    text: str
    job_levels: list[str]
    last_updated: str


@dataclass
class ParsedCorpus:
    sections: list[PolicySection]
    last_updated: str


def parse_policy_corpus(markdown_text: str) -> ParsedCorpus:
    """Pure function, no I/O — testable offline. Splits on `## §<id> <title>`
    headings; expects a `<!-- job_levels: a, b, c -->` comment as the first
    line of each section's body."""
    last_updated_match = _LAST_UPDATED_RE.search(markdown_text)
    last_updated = last_updated_match.group(1) if last_updated_match else "unknown"

    lines = markdown_text.splitlines()
    sections: list[PolicySection] = []
    current_id: str | None = None
    current_title = ""
    current_job_levels: list[str] = []
    current_body: list[str] = []

    def flush():
        if current_id is not None:
            sections.append(
                PolicySection(
                    section_id=current_id,
                    title=current_title,
                    text="\n".join(current_body).strip(),
                    job_levels=current_job_levels,
                    last_updated=last_updated,
                )
            )

    for line in lines:
        heading_match = _SECTION_HEADING_RE.match(line)
        if heading_match:
            flush()
            current_id, current_title = heading_match.group(1), heading_match.group(2)
            current_job_levels = []
            current_body = []
            continue

        job_levels_match = _JOB_LEVELS_RE.match(line.strip())
        if job_levels_match and current_id is not None and not current_job_levels:
            current_job_levels = [lvl.strip() for lvl in job_levels_match.group(1).split(",")]
            continue

        if current_id is not None:
            current_body.append(line)

    flush()
    return ParsedCorpus(sections=sections, last_updated=last_updated)


_QDRANT_ID_NAMESPACE = uuid.UUID("6f6a2e2a-6b3e-4b8f-9b0e-7a1c2d3e4f50")


def _section_point_id(section_id: str) -> str:
    """Qdrant point ids must be an unsigned int or a UUID — deterministic
    uuid5 so re-ingesting the same section_id overwrites its point instead
    of duplicating it."""
    return str(uuid.uuid5(_QDRANT_ID_NAMESPACE, section_id))


def _qdrant_collection(collection_name: str):
    from qdrant_client import QdrantClient, models
    from qdrant_client.http.exceptions import UnexpectedResponse

    client = QdrantClient(url=os.environ["QDRANT_URL"], api_key=os.environ["QDRANT_API_KEY"])
    existing = {c.name for c in client.get_collections().collections}
    if collection_name not in existing:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(size=1536, distance=models.Distance.COSINE),  # text-embedding-3-small
        )

    # Qdrant requires a payload index to filter by a field (the job-level
    # scoping filter in rag/retriever.py) — without this, every filtered
    # query 400s with "Index required but not found". create_payload_index
    # is called unconditionally so a pre-existing collection (created before
    # this index was added) gets it too; already-exists is swallowed for
    # idempotency on repeat ingests.
    try:
        client.create_payload_index(
            collection_name=collection_name, field_name="job_levels", field_schema=models.PayloadSchemaType.KEYWORD,
        )
    except UnexpectedResponse as exc:
        if "already exists" not in str(exc).lower():
            raise

    return client


def ingest(corpus_path: Path = CORPUS_PATH, collection_name: str | None = None) -> int:
    """Parses the corpus, embeds each section, upserts to Qdrant.
    Returns the number of sections upserted."""
    from qdrant_client import models

    collection_name = collection_name or os.environ.get("QDRANT_COLLECTION_NAME", "corporate-travel-policy")
    parsed = parse_policy_corpus(corpus_path.read_text(encoding="utf-8"))

    embedder = Embedder()
    vectors = embedder.embed_texts([s["text"] for s in parsed.sections])

    client = _qdrant_collection(collection_name)
    points = [
        models.PointStruct(
            id=_section_point_id(section["section_id"]),
            vector=vector,
            payload={
                "section_id": section["section_id"],
                "title": section["title"],
                "text": section["text"],
                "job_levels": section["job_levels"],
                "last_updated": section["last_updated"],
            },
        )
        for section, vector in zip(parsed.sections, vectors)
    ]
    client.upsert(collection_name=collection_name, points=points)

    from trip_planner.cache.semantic_cache import get_default_cache

    get_default_cache().invalidate_all()  # every cached policy answer may now be stale (spec §3.9)

    return len(points)


if __name__ == "__main__":
    count = ingest()
    print(f"Upserted {count} policy sections from {CORPUS_PATH.relative_to(REPO_ROOT)}")
