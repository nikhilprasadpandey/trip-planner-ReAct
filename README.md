# Corporate Travel Planner & Policy-Compliance Agent

A production-minded, multi-agent ReAct system: an employee asks for a trip,
the system finds live flights, checks weather, checks the fare against
corporate travel policy (Qdrant RAG, scoped by job level), and routes
anything out-of-policy for human approval before booking.

Full spec: [`enterprise_agent_build_spec.md`](enterprise_agent_build_spec.md).
Architecture docs: [`docs/architecture.md`](docs/architecture.md) ·
[`docs/HLD.md`](docs/HLD.md) · [`docs/LLD.md`](docs/LLD.md) ·
[`docs/runbook_audit_trace.md`](docs/runbook_audit_trace.md).

> **Status**: M0–M4 complete (core flow, enterprise policy/guardrails/booking,
> dual cost ledger, caching, the SQLAlchemy audit store, and architecture docs).
> See `enterprise_agent_build_spec.md` for the full spec this was built against.

## Stack

Python 3.13 · LangChain · LangGraph · FastAPI · Streamlit · Qdrant · MCP ·
Langfuse · SQLAlchemy · OpenAI (gpt-4.1 + text-embedding-3-small)

## Project layout

```
config/                  guardrail policy, flight-provider toggle, model prices
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
cp .env.example .env             # fill in keys — see comments in the file
```

Required live keys to run the app for real: `OPENAI_API_KEY` (agent LLM
calls, gpt-4.1, and embeddings, text-embedding-3-small — one key for
both), `QDRANT_URL` + `QDRANT_API_KEY` (policy RAG). `DUFFEL_ACCESS_TOKEN`
or `AVIATIONSTACK_API_KEY` for flight pricing (`FLIGHT_PROVIDER` picks
which). `LANGFUSE_*` and a real `AUDIT_DB_URL` (Postgres) are optional —
the app runs fine without them (SQLite + no tracing).

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

### API endpoints

- `POST /trip-requests` — plan a trip end to end (weather, fares, policy check, approval routing)
- `POST /approvals/{trace_id}/grant` / `/reject` — decide a pending approval
- `POST /trip-requests/{trace_id}/book` — the one write action (stub), blocked without a granted approval
- `POST /policy-questions` — ask the Policy Agent a general question (semantic-cached)
- `GET /audit/{trace_id}` — the runbook endpoint: full expense-audit record for one request

Identity is a mock persona header (`X-Employee-Id`, one of `employee-ic-001` /
`employee-mgr-001` / `employee-dir-001`) — see `src/trip_planner/api/auth.py`.
The Streamlit sidebar has a persona switcher; use it to replay the same
request as different job levels and watch the policy/approval outcome
correctly diverge (spec §8 acceptance criterion).

## Tests

```bash
pytest
```

Runs fully offline against fixtures in `tests/fixtures/` and fakes/mocks
for Qdrant, embeddings, and OpenAI — no live keys required. A single
skipped test exercises a real end-to-end run when `OPENAI_API_KEY` and
`DUFFEL_ACCESS_TOKEN` are set.

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
