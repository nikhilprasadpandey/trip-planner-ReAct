#!/usr/bin/env python
"""Seed/refresh the Pinecone policy index from rag/corpus/policy_source.md.

Usage: python scripts/seed_policy_corpus.py
Requires PINECONE_API_KEY and OPENAI_API_KEY in the environment (.env).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trip_planner.rag.ingest import ingest  # noqa: E402

if __name__ == "__main__":
    count = ingest()
    print(f"Upserted {count} policy sections.")
