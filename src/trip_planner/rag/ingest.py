"""Ingestion pipeline for the corporate travel policy corpus (spec §3.3):
chunk by policy section, embed, upsert to Pinecone with metadata (section
id, job-level applicability, last-updated date).

Run: python -m trip_planner.rag.ingest
"""
from __future__ import annotations

import os
import re
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


def _pinecone_index(index_name: str):
    from pinecone import Pinecone, ServerlessSpec

    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    if index_name not in [idx["name"] for idx in pc.list_indexes()]:
        pc.create_index(
            name=index_name,
            dimension=1536,  # text-embedding-3-small
            metric="cosine",
            spec=ServerlessSpec(
                cloud=os.environ.get("PINECONE_CLOUD", "aws"),
                region=os.environ.get("PINECONE_REGION", "us-east-1"),
            ),
        )
    return pc.Index(index_name)


def ingest(corpus_path: Path = CORPUS_PATH, index_name: str | None = None) -> int:
    """Parses the corpus, embeds each section, upserts to Pinecone.
    Returns the number of sections upserted."""
    index_name = index_name or os.environ.get("PINECONE_INDEX_NAME", "corporate-travel-policy")
    parsed = parse_policy_corpus(corpus_path.read_text(encoding="utf-8"))

    embedder = Embedder()
    vectors = embedder.embed_texts([s["text"] for s in parsed.sections])

    index = _pinecone_index(index_name)
    upserts = [
        {
            "id": section["section_id"],
            "values": vector,
            "metadata": {
                "section_id": section["section_id"],
                "title": section["title"],
                "text": section["text"],
                "job_levels": section["job_levels"],
                "last_updated": section["last_updated"],
            },
        }
        for section, vector in zip(parsed.sections, vectors)
    ]
    index.upsert(vectors=upserts)
    return len(upserts)


if __name__ == "__main__":
    count = ingest()
    print(f"Upserted {count} policy sections from {CORPUS_PATH.relative_to(REPO_ROOT)}")
