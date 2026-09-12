# Corporate Travel Planner & Policy-Compliance Agent

A production-minded, multi-agent ReAct system: an employee asks for a trip,
the system finds live flights, checks weather, checks the fare against
corporate travel policy (Qdrant RAG, scoped by job level), and routes
anything out-of-policy for human approval before booking.

Full spec: [`enterprise_agent_build_spec.md`](enterprise_agent_build_spec.md).
Architecture docs: [`docs/`](docs/) (added in build milestone M4).

> **Status**: project scaffold (M0) complete. See `enterprise_agent_build_spec.md`
> and the approved build plan for the M1–M4 sequence this repo is built out in.

## Stack

Python 3.13 · LangChain · LangGraph · FastAPI · Streamlit · Qdrant · MCP ·
Langfuse · SQLAlchemy · Anthropic Claude

## Project layout

```
config/                  guardrail policy, flight-provider toggle, model prices
src/trip_planner/
  api/                    FastAPI gateway (authN/authZ, rate limiting)
  orchestrator/           LangGraph state graph (planning + ReAct)
  agents/                 Orchestrator / Flight / Weather / Policy agents
  tools/                  LangChain tools (flight, weather, policy, booking)
  mcp_servers/            MCP servers: free-tools (geocode/weather/flights),
                          booking (book_flight, approval-gated)
  rag/                    Qdrant ingestion + retrieval, policy corpus
  guardrails/             approval gate, prompt-injection, groundedness, allowlist
  cost/                   dual cost ledger (agent compute vs. business fare cost)
  cache/                  route cache (exact-match) + semantic cache (policy Q&A)
  audit/                  append-only audit store (expense-audit trail)
  observability/          Langfuse tracing
streamlit_app/            UI: trip request, persona selector, trace/audit view
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

## Running (once M1+ lands)

```bash
# 1. MCP servers
python -m trip_planner.mcp_servers.free_tools_server
python -m trip_planner.mcp_servers.booking_server

# 2. API gateway
uvicorn trip_planner.api.main:app --reload

# 3. UI
streamlit run streamlit_app/app.py
```

## Tests

```bash
pytest
```

Runs fully offline against fixtures in `tests/fixtures/` (mock
Aviationstack/Duffel/Qdrant responses) — no API keys required. Live keys
in `.env` are only needed to run the app itself.

## Config

- `config/guardrails.yaml` — spend caps, approval routing, and cabin-class
  eligibility by job level. Edit this to change policy, not code.
- `config/flight_provider.yaml` — toggle `duffel` (test mode, dev) vs.
  `aviationstack` (live, limited free quota) flight pricing.
- `config/model_prices.yaml` — per-model token price table for the
  agent-operating-cost side of the dual cost ledger.
