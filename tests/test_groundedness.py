from __future__ import annotations

from trip_planner.guardrails.groundedness import check_groundedness


def test_answer_citing_retrieved_section_is_grounded():
    result = check_groundedness("This fare is out of policy per §3a.", retrieved_section_ids=["3a", "4"])
    assert result["is_grounded"] is True
    assert result["cited_section_ids"] == ["3a"]


def test_answer_with_no_citation_is_not_grounded():
    result = check_groundedness("This fare seems fine to me.", retrieved_section_ids=["3a", "4"])
    assert result["is_grounded"] is False
    assert result["cited_section_ids"] == []


def test_citation_without_section_symbol_still_counts():
    result = check_groundedness("Per section 3b this is over the cap.", retrieved_section_ids=["3b"])
    assert result["is_grounded"] is True
