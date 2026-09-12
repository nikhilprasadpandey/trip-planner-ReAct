"""Offline test for the policy-corpus parser (no Pinecone/OpenAI needed)."""
from __future__ import annotations

from trip_planner.rag.ingest import CORPUS_PATH, parse_policy_corpus


def test_parses_real_corpus_into_sections_with_job_level_metadata():
    parsed = parse_policy_corpus(CORPUS_PATH.read_text(encoding="utf-8"))

    assert parsed.last_updated == "2026-09-01"
    section_ids = {s["section_id"] for s in parsed.sections}
    assert {"1", "2a", "2b", "2c", "3a", "3b", "3c", "4", "5a", "5b", "5c", "6"} <= section_ids

    ic_cap_section = next(s for s in parsed.sections if s["section_id"] == "3a")
    assert ic_cap_section["job_levels"] == ["ic"]
    assert "$600" in ic_cap_section["text"]

    shared_section = next(s for s in parsed.sections if s["section_id"] == "4")
    assert shared_section["job_levels"] == ["ic", "manager", "director"]


def test_parse_handles_minimal_synthetic_input():
    md = (
        "<!-- last_updated: 2026-01-01 -->\n"
        "## §9 Test Section\n"
        "<!-- job_levels: manager -->\n"
        "Body text here.\n"
    )
    parsed = parse_policy_corpus(md)
    assert len(parsed.sections) == 1
    assert parsed.sections[0] == {
        "section_id": "9",
        "title": "Test Section",
        "text": "Body text here.",
        "job_levels": ["manager"],
        "last_updated": "2026-01-01",
    }
