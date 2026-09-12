# Corporate Travel Planner & Policy-Compliance Agent

A production-minded, multi-agent **ReAct** system: an employee asks for a
trip, the system finds live flights, checks weather, checks the fare
against corporate travel policy (Qdrant RAG, scoped by job level), and
routes anything out-of-policy for human approval before booking.

Full spec: [`enterprise_agent_build_spec.md`](enterprise_agent_build_spec.md).
Architecture docs: [`docs/architecture.md`](docs/architecture.md) ·
[`docs/HLD.md`](docs/HLD.md) · [`docs/LLD.md`](docs/LLD.md) ·
[`docs/runbook_audit_trace.md`](docs/runbook_audit_trace.md).
Working conventions for anyone (human or Claude Code) editing this repo:
[`CLAUDE.md`](CLAUDE.md).

> **Status**: M0–M4 complete (core flow, enterprise policy/guardrails/booking,
> dual cost ledger, caching, the SQLAlchemy audit store, and architecture docs),
> plus a full pass of live acceptance testing with real credentials — see
> `CLAUDE.md`'s deviation notes for where the as-built system differs from
> the original spec (Qdrant instead of Pinecone, OpenAI instead of Anthropic).

## Stack

Python 3.13 · LangChain · LangGraph · FastAPI · Streamlit · Qdrant · MCP ·
Langfuse · SQLAlchemy · OpenAI (`gpt-4.1` + `text-embedding-3-small`)

## Project layout

```
config/                  guardrail policy, flight-provider toggle, model prices
docs/                     architecture diagram, HLD, LLD, audit runbook
src/trip_planner/
  api/                    FastAPI gateway (authN/authZ, rate limiting)
  orchestrator/           LangGraph state graph (planning + ReAct + reflection)
  agents/                 Orchestrator / Flight / Weather / Policy agents
  tools/                  LangChain tools (flight, weather, policy, booking)
  mcp_servers/            MCP servers: trip-lookup (geocode/weather/flights),
                          booking (book_flight, approval-gated)
  rag/                    Qdrant ingestion + retrieval, policy corpus
  guardrails/             approval gate, prompt-injection, groundedness, allowlist,
                          spend-cap/cabin-class thresholds
  cost/                   dual cost ledger (agent compute vs. business fare cost)
  cache/                  route cache (exact-match) + semantic cache (policy Q&A)
  audit/                  append-only SQLAlchemy audit store + PII redaction
  observability/          Langfuse tracing
streamlit_app/            UI: persona selector, trip request, policy Q&A, cost/audit view
tests/                    offline dry-run tests against fixtures (no live keys needed)
scripts/                  policy-corpus seeding, MCP server launch helpers
```

## Setup

```bash
python3.13 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env             # fill in keys — see the table below
```

### Environment variables

All of these live in `.env` (gitignored — never commit real values; `.env.example`
is the safe, blank-valued template). Only three are required to run the app
for real; everything else has a working default or is optional.

| Variable | Required? | Default | What it's for |
|---|---|---|---|
| `OPENAI_API_KEY` | **Yes** | — | Agent LLM calls (`gpt-4.1`) **and** embeddings (`text-embedding-3-small`) — one key, one provider, for both |
| `QDRANT_URL` | **Yes** | — | Qdrant Cloud (or self-hosted) cluster endpoint for the policy corpus |
| `QDRANT_API_KEY` | **Yes** | — | Qdrant auth |
| `QDRANT_COLLECTION_NAME` | No | `corporate-travel-policy` | Qdrant collection name |
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | OpenAI embedding model for policy retrieval |
| `FLIGHT_PROVIDER` | No | `duffel` | `duffel` (test mode, safe to hammer during dev) or `aviationstack` (live, ~100 free requests total — see FAQ) |
| `DUFFEL_ACCESS_TOKEN` | Only if using Duffel | — | Duffel test-mode token (starts `duffel_test_...`) |
| `AVIATIONSTACK_API_KEY` | Only if using Aviationstack | — | Aviationstack key |
| `NOMINATIM_URL` | No | public Nominatim | Override for a self-hosted geocoder (public instance's usage policy is light-use only) |
| `OPEN_METEO_URL` | No | public Open-Meteo | Override for Open-Meteo's paid/higher-volume tier |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | No | — | Enables Langfuse tracing; unset = tracing silently no-ops |
| `LANGFUSE_HOST` | No | `https://cloud.langfuse.com` | Langfuse region/self-hosted endpoint |
| `AUDIT_DB_URL` | No | `sqlite:///./data/audit.db` | Swap for `postgresql+psycopg://user:pass@host:5432/dbname` in prod — no code change either way |
| `MOCK_AUTH_ENABLED` | No | `true` | Real OIDC isn't wired up yet (see FAQ) — must stay `true` for now |
| `API_GATEWAY_URL` | No | `http://localhost:8000` | Where the Streamlit UI looks for the API gateway |
| `LOG_LEVEL` | No | `INFO` | Not yet read anywhere — reserved |

## Running

```bash
# 1. Seed the policy corpus into Qdrant (once, or after editing the corpus)
python scripts/seed_policy_corpus.py

# 2. MCP servers
python -m trip_planner.mcp_servers.trip_lookup_server
python -m trip_planner.mcp_servers.booking_server

# 3. API gateway
uvicorn trip_planner.api.main:app --reload

# 4. UI
streamlit run streamlit_app/app.py
```

The two MCP servers in step 2 are for standalone testing/inspection only —
the API gateway spawns them itself over stdio as needed (`mcp_client.py`),
so step 2 is optional for normal use.

### API endpoints

| Method | Path | What it does |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `POST` | `/trip-requests` | Plan a trip end to end (weather, fares, policy check, approval routing) |
| `POST` | `/approvals/{trace_id}/grant` \| `/reject` | Decide a pending approval |
| `POST` | `/trip-requests/{trace_id}/book` | The one write action (stub), blocked without a granted approval |
| `POST` | `/policy-questions` | Ask the Policy Agent a general question (semantic-cached) |
| `GET` | `/audit/{trace_id}` | The runbook endpoint: full expense-audit record for one request |

Identity is a mock persona header (`X-Employee-Id`, one of `employee-ic-001` /
`employee-mgr-001` / `employee-dir-001`) — see `src/trip_planner/api/auth.py`.
The Streamlit sidebar has a persona switcher; use it to replay the same
request as different job levels and watch the policy/approval outcome
correctly diverge (spec §8 acceptance criterion — verified live, see FAQ).

## Tests

```bash
pytest
```

Runs fully offline against fixtures in `tests/fixtures/` and fakes/mocks
for Qdrant, embeddings, and OpenAI — no live keys required. One test
(`test_run_trip_planning_end_to_end_live`) exercises a real end-to-end run
and is skipped unless `OPENAI_API_KEY` and `DUFFEL_ACCESS_TOKEN` are set.

## Config

- `config/guardrails.yaml` — spend caps, approval routing, and cabin-class
  eligibility by job level. Edit this to change policy, not code.
- `config/flight_provider.yaml` — toggle `duffel` (test mode, dev) vs.
  `aviationstack` (live, limited free quota) flight pricing.
- `config/model_prices.yaml` — per-model token price table for the
  agent-operating-cost side of the dual cost ledger.

When you edit `config/guardrails.yaml`'s caps, mirror the change in
`src/trip_planner/rag/corpus/policy_source.md` and re-run
`scripts/seed_policy_corpus.py` — the Policy Agent's grounded explanation
should always agree with the deterministic threshold check.

## FAQ / Troubleshooting

**The weather section is empty, or the agent says the trip is "too far in
the future."**
Open-Meteo's daily forecast only covers ~16 days ahead of *today*, and the
Weather Agent doesn't otherwise know the actual current date (LLMs don't
reliably know "today" on their own). The orchestrator tells it today's
date explicitly, so this should self-correct — but if you're testing a
`departure_date` more than ~16 days out, expect the agent to say plainly
that it's too far out for a forecast rather than inventing one. That's
correct behavior, not a bug.

**Flight search says "pricing unavailable."**
Check `flight_search.reason` in the response — it's always one of: missing
provider credentials, a timeout, a non-2xx response, or (Aviationstack
specifically) quota exhaustion (~100 free requests total). This is
deliberate graceful degradation (spec §4/§8), not a crash. Duffel test mode
(the default) doesn't have this quota problem — switch `FLIGHT_PROVIDER`
back to `duffel` if you're testing repeatedly.

**Why does `/policy-questions` sometimes say `cache_hit: false` even for a
very similar question?**
The semantic cache matches on cosine similarity over `text-embedding-3-small`
vectors, with a threshold of `0.70` (`cache/semantic_cache.py`) — chosen
from real measurements: paraphrases of the same policy question scored
0.70–0.78, unrelated questions scored 0.35–0.36. A `false` on a question
that reads as "obviously the same" to you may just be genuinely more
different in embedding space than expected; it's not a broken cache.

**Do I really need both `OPENAI_API_KEY` and a separate LLM setup?**
No — there's only one LLM provider in this app (OpenAI, `gpt-4.1`), used by
every agent, plus the same key for embeddings. If you're also using Claude
Code to work on this repo, that's a separate, unrelated credential — Claude
Code doesn't need to be (and isn't) involved in the running app itself.

**The docs mention Pinecone/Anthropic — but the code uses Qdrant/OpenAI?**
The original spec (`enterprise_agent_build_spec.md`) named Pinecone and
Anthropic Claude; both were swapped during the build per direct user
instruction (Qdrant credentials and an OpenAI key were provided instead of
Pinecone/Anthropic ones). The spec doc is kept as-is as the historical
source document; `CLAUDE.md` documents the deviation and why.

**How do I test the approve → book flow without waiting for a real
out-of-policy fare?**
Request a cabin class above what a persona is eligible for (e.g.
`employee-ic-001` requesting `business`) — the reflection loop will retry
down through cabin classes (bounded by `max_reflection_retries` in
`config/guardrails.yaml`, default 2) and land on a pending approval if it
still can't get under cap. Grant it via `POST /approvals/{trace_id}/grant`
as a different (e.g. manager) persona, then `POST
/trip-requests/{trace_id}/book`.

**Can an employee trick the Policy Agent into revealing another job level's
spend cap?**
No — `job_level` is baked into the policy-retrieval tool at construction
time from the *authenticated* identity, not exposed as an LLM-fillable
parameter (`tools/policy_tools.py`). The model can't ask for a different
tier's clauses no matter how the question is phrased.

**What's a `trace_id` for, and how do I audit one request?**
See [`docs/runbook_audit_trace.md`](docs/runbook_audit_trace.md) — short
version: `GET /audit/{trace_id}` returns the full expense-audit record
(fares considered, policy applied, approval outcome, both cost numbers,
full call sequence) for that one request.

**How do I reset the audit database / clear test data?**
SQLite: delete `data/audit.db` (recreated automatically on next write).
Postgres: `DELETE FROM audit_events;` (or drop/recreate the table — the
schema is created automatically on first use). There's no code-level
"reset" command by design — this is meant to be an append-only, auditable
store.

**Port 8000 (or the MCP servers) is already in use.**
`uvicorn trip_planner.api.main:app --reload --port <other-port>`, and set
`API_GATEWAY_URL` in `.env` to match for the Streamlit UI to find it. The
MCP servers run over stdio (spawned as subprocesses), not a network port,
so they don't have this problem.

**Real OIDC/SSO isn't wired up — is that a gap?**
No, it's intentional for this build (spec's own guidance: leave real
IdP/SSO out of the live build, design for it). `api/auth.py`'s
`resolve_identity` has the same shape a real OIDC client would (bearer
token → `EmployeeIdentity`), so swapping it in later is a drop-in
replacement of that one function, not a rewrite.
