# Eval Suite

`tests/` (offline, fakes/fixtures, no live keys) checks plumbing —
guardrail wiring, cache scoping, cost math. It cannot catch a real quality
regression in the Policy Agent's actual answers, because the LLM call
itself is never made.

`scripts/run_policy_eval.py` is the other half: a **live** eval suite —
14 golden questions run against the real Policy Agent (OpenAI + Qdrant),
scored against expected values verified directly from
[`rag/corpus/policy_source.md`](../src/trip_planner/rag/corpus/policy_source.md)
and [`config/guardrails.yaml`](../config/guardrails.yaml), not guessed.

## Running it

```bash
python scripts/seed_policy_corpus.py   # once, or after editing the corpus
python scripts/run_policy_eval.py
```

Requires `OPENAI_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY` in the
environment. Exits non-zero if any question fails, so it can be wired into
a CI gate later.

## Methodology

**Scored by structured result, not prose text match** — the same
principle a Text-to-SQL eval uses when it checks the returned rows instead
of diffing SQL strings. Each question checks the API's own guardrail
fields, not the LLM's sentence:

- `grounded` — did the Policy Agent's citation check pass (spec §3.4)?
- `cited_section_ids` — does it actually cite one of the expected corpus
  sections, not just *a* section?
- `cache_hit` — for the one paraphrase question, did the semantic cache
  actually fire (spec §3.9)?
- `blocked` (adversarial only) — was the request rejected before it ever
  reached the LLM?

## The 14 questions

| ID | Category | Job level | Tests |
|---|---|---|---|
| E1–E3 | Easy | ic / manager / director | Single-fact lookup: domestic cap, cabin eligibility, preferred carriers |
| M1–M4 | Medium | ic / manager / director | Connecting a fact to its consequence: cabin ineligibility, advance-booking window, international cap, approval routing |
| H1 | Hard | ic | Semantic-cache hit on a paraphrase of E1 (depends on E1 running first in the same process) |
| H2–H3 | Hard | manager / director | Connecting cabin eligibility to an approval requirement, not just restating a cap |
| A1–A2 | Adversarial | ic | Prompt-injection attempts — must be rejected pre-LLM, not answered |
| A3–A4 | Adversarial | manager / director | Off-topic but benign questions — must come back `grounded: false`, never a fabricated answer |

## Latest run

```
Easy         3/3
Medium       4/4
Hard         3/3
Adversarial  4/4
Total: 14/14
```

Run live against real OpenAI + Qdrant on 2026-09-13. Re-run after editing
the corpus, the guardrail config, or the Policy Agent's prompt — and keep
this list in sync with `scripts/run_policy_eval.py`'s `GOLDEN_SET` if the
score changes.

## Known limitation

Caught during the first live run, not assumed: the script's `print()`
output used `✓` and em-dashes, which crash with `UnicodeEncodeError`
on a default Windows console (cp1252). Fixed by forcing UTF-8 stdout at
the top of the script — worth knowing if you extend it and add more
non-ASCII output.
