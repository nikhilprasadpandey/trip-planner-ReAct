# CLAUDE.md

Guidance for Claude Code (and future sessions) working in this repository.

## What this is

Corporate Travel Planner & Policy-Compliance Agent — a production-minded,
multi-agent ReAct system. Full requirements: `enterprise_agent_build_spec.md`
(source of truth — read it before making architectural changes). Build plan
and milestones: see the plan referenced in project memory / conversation
history (M0–M4).

**Deviations from the spec doc, as-built** (the spec names Anthropic Claude
+ Pinecone + OpenAI direct throughout):
- **Vector DB**: Qdrant Cloud, not Pinecone — user provided Qdrant
  credentials directly. `rag/retriever.py` keeps a Pinecone-shaped internal
  seam (`IndexClient` Protocol) so another swap later doesn't ripple
  outward.
- **LLM + embeddings**: OpenAI (`gpt-4.1` for all agent reasoning,
  `text-embedding-3-small` for RAG), not Anthropic Claude — user provided
  an OpenAI key and explicitly opted out of providing an Anthropic key.
  One provider, one key, for both. `agents/base.py` is the single place
  the model client is constructed (`ChatOpenAI`) — swapping providers
  again means changing that one file plus `config/model_prices.yaml`'s
  price table, not touching individual agents.

## Stack

Python 3.13, LangChain + LangGraph (orchestration), FastAPI (API gateway),
Streamlit (UI), Qdrant (policy RAG), MCP (`mcp` SDK, two servers), Langfuse
(observability), SQLAlchemy (audit store), OpenAI (LLM + embeddings).

## Key architectural rules (do not violate silently)

- **Every agent's tool set is allow-listed at construction** (`agents/base.py`)
  — never let an agent import/call a tool outside its declared list.
- **`book_flight` is never called without an approval record for that
  `trace_id`** — this is the core guardrail (`guardrails/approval_gate.py`).
  Any change touching the booking path must preserve this invariant and its
  test (`tests/test_approval_gate.py`).
- **One `trace_id` per trip-planning request**, propagated through every
  agent, tool call, cache hit/miss, guardrail check, and LLM call — it's the
  join key across the audit store and Langfuse. Don't introduce a second id.
- **Flight provider is swappable** (`config/flight_provider.yaml` /
  `FLIGHT_PROVIDER` env var: `duffel` test mode vs `aviationstack` live).
  Never hardcode against one provider's response shape outside
  `tools/flight_tools.py`.
- **Policy retrieval is job-level-scoped** — Qdrant queries from the Policy
  Agent must filter by the requester's job level (metadata filter), re-checked
  at the retrieval call itself, not only at the API gateway.
- **Cache keys**: flight-route cache by route+date (safe to share across
  employees); policy semantic-cache by job level (never serve one tier's
  cached answer to another).
- **Guardrail thresholds live in `config/guardrails.yaml`**, not in code.

## Running locally

See `README.md` for the up-to-date commands (MCP servers, FastAPI gateway,
Streamlit app, tests). Tests run offline against fixtures in
`tests/fixtures/` — no live API keys required for `pytest`.

## Conventions

- New agents go in `src/trip_planner/agents/`, subclass the allow-listed
  base in `agents/base.py`.
- New tools go in `src/trip_planner/tools/`, wired to MCP servers in
  `src/trip_planner/mcp_servers/`.
- Config changes (spend caps, provider toggles, prices) go in `config/*.yaml`
  — don't hardcode values the spec calls out as operator-adjustable.
