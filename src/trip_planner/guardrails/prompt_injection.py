"""Input guardrail (spec §3.4): prompt-injection detection on user input and
on any retrieved policy text / tool observation fed back into an LLM call.

Heuristic pattern scan — cheap, deterministic, runs on every input with no
extra LLM call. Catches the common injection phrasings; it is not a
substitute for a classifier model in a real deployment, but is enough to
exercise the guardrail path end to end for this build (flip
`prompt_injection_check_enabled: false` in config/guardrails.yaml to disable).
"""
from __future__ import annotations

import re
from typing import TypedDict

from trip_planner.config_loader import guardrails_config

_SUSPICIOUS_PATTERNS = [
    r"ignore (all|previous|the above|earlier) instructions",
    r"disregard (all|previous|the above|earlier) instructions",
    r"you are now",
    r"new system prompt",
    r"reveal (your |the )?(system prompt|instructions)",
    r"act as (an?|the) (?!employee|manager|director)\w+",  # "act as a ..." (excluding the domain roles we expect)
    r"do anything now",
    r"jailbreak",
    r"\bsudo\b",
    r"override (your |the )?(guardrails|policy|approval)",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _SUSPICIOUS_PATTERNS]


class PromptInjectionResult(TypedDict):
    is_suspicious: bool
    matched_patterns: list[str]


class PromptInjectionDetectedError(Exception):
    """Raised by callers that want to reject the request outright on a
    match, rather than just inspecting the PromptInjectionResult — every
    user-facing entry point that accepts free text should raise this on a
    hit (see orchestrator/graph.py's run_trip_planning and
    agents/policy_agent.py's answer_policy_question)."""


def check_prompt_injection(text: str) -> PromptInjectionResult:
    if not guardrails_config().get("prompt_injection_check_enabled", True):
        return PromptInjectionResult(is_suspicious=False, matched_patterns=[])

    matched = [pattern.pattern for pattern in _COMPILED if pattern.search(text)]
    return PromptInjectionResult(is_suspicious=bool(matched), matched_patterns=matched)


def reject_if_suspicious(text: str, trace_id: str) -> None:
    """Convenience wrapper: check_prompt_injection + raise + audit-log in
    one call, so every free-text entry point applies the guardrail
    identically instead of re-implementing the check/raise/log sequence."""
    from trip_planner.audit.store import record_event

    result = check_prompt_injection(text)
    if result["is_suspicious"]:
        record_event(trace_id, "prompt_injection_blocked", {"text": text, "matched": result["matched_patterns"]})
        raise PromptInjectionDetectedError(f"Request blocked by input guardrail: {result['matched_patterns']}")
