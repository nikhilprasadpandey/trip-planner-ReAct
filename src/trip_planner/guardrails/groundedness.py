"""Output guardrail (spec §3.4): the Policy Agent's answer must be grounded
in a retrieved clause — it must not assert a policy rule that wasn't
actually retrieved. Checked by citation: does the answer text reference at
least `groundedness_min_citations` of the section_ids that were actually
returned by the retriever this turn?

This is a citation check, not a semantic-entailment model — cheap, fast,
deterministic, and good enough to catch the failure mode the spec calls out
(the model asserting a cap/rule it didn't actually look up). A production
version could add an LLM-judge pass on top; not needed for this build.
"""
from __future__ import annotations

import re
from typing import TypedDict

from trip_planner.config_loader import guardrails_config


class GroundednessResult(TypedDict):
    is_grounded: bool
    cited_section_ids: list[str]
    min_required: int


def _section_id_pattern(section_id: str) -> re.Pattern:
    # section ids look like "3a", "6" — match "§3a" or "3a" as a whole token.
    return re.compile(rf"(§\s*)?{re.escape(section_id)}\b")


def check_groundedness(answer_text: str, retrieved_section_ids: list[str]) -> GroundednessResult:
    min_required = guardrails_config().get("groundedness_min_citations", 1)
    cited = [sid for sid in retrieved_section_ids if _section_id_pattern(sid).search(answer_text)]
    return GroundednessResult(
        is_grounded=len(cited) >= min_required,
        cited_section_ids=cited,
        min_required=min_required,
    )
