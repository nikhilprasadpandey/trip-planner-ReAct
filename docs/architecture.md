# Architecture

Corporate Travel Planner & Policy-Compliance Agent — a multi-agent ReAct
system built on LangGraph, with MCP as the tool-hosting boundary, Qdrant
for policy RAG, and a guardrail/audit/cost layer wrapped around all of it.

Full requirements: [`../enterprise_agent_build_spec.md`](../enterprise_agent_build_spec.md).
As-built deviations from that spec (vector DB, LLM/embeddings provider):
[`../CLAUDE.md`](../CLAUDE.md).

A polished version of the diagram below is also published as a standalone
page: **[Architecture Diagram (Artifact)](https://claude.ai/code/artifact/30854ccb-1e21-4348-aa35-cd1dae44832a)**
— private by default; this markdown version is the durable, in-repo source
of truth if that link's access changes.

---

## 1. System overview

An employee submits a trip request through Streamlit. The FastAPI gateway
authenticates them (mock persona header today; OIDC-shaped interface for
later) and hands the request to a LangGraph orchestrator, which runs three
ReAct agents in sequence — Weather, Flight, Policy — with a reflection edge
back from Policy to Flight when a fare is out of policy. Every step is
wrapped in guardrails, logged to an append-only audit store, costed on a
dual ledger, and (optionally) traced in Langfuse. The one mutating action
in the system — booking — is a separate, higher-scrutiny MCP server gated
by an approval record.

```mermaid
flowchart TB
    Employee(["Employee"]) --> UI["Streamlit UI\n(persona switcher, policy Q&A)"]
    UI -->|"HTTP + X-Employee-Id"| GW["FastAPI Gateway\nauthN (mock OIDC) · rate limiting"]

    GW --> ORCH["Orchestrator\nLangGraph StateGraph"]

    subgraph Agents["ReAct Agents (tool allow-listed at construction)"]
        WA["Weather Agent"]
        FA["Flight Agent"]
        PA["Policy Agent"]
    end

    ORCH --> WA
    ORCH --> FA
    ORCH --> PA
    PA -. "reflection: cheaper/lower-cabin retry" .-> FA

    subgraph MCP["MCP servers"]
        TripLookup["trip-lookup server\ngeocode · get_weather · search_flights"]
        Booking["booking server\nbook_flight (approval-gated)"]
    end

    WA --> TripLookup
    FA --> TripLookup
    TripLookup -->|Nominatim + Open-Meteo| Weather[("Weather/Geocoding\n(free APIs)")]
    TripLookup -->|Duffel test / Aviationstack live| Flights[("Flight pricing\n(provider-swappable)")]

    PA --> RAG["Policy retrieval tool\n(job_level baked in, not LLM-fillable)"]
    RAG --> Qdrant[("Qdrant Cloud\npolicy corpus, job-level filtered")]
    RAG --> Embed["OpenAI embeddings\ntext-embedding-3-small"]

    ORCH --> GR["Guardrails\napproval gate · prompt-injection ·\ngroundedness · allow-list · thresholds"]
    GR --> Approval[("Approval store\n(in-memory M3, DB-shaped)")]
    Approval --> Booking

    ORCH --> Cache["Cache layer"]
    Cache --> RouteCache["Route cache\n(exact-match TTL)"]
    Cache --> SemCache["Semantic cache\n(policy Q&A, job-level-scoped)"]

    ORCH --> Cost["Cost ledger\nagent compute $ vs. fare $"]
    ORCH --> Audit["Audit store\nSQLAlchemy, append-only, PII-redacted"]
    ORCH -. optional .-> Langfuse[("Langfuse\ntracing")]

    Booking -->|"book_flight\n(stub, one write action)"| BookingSys[("Booking system\n(stubbed)")]

    classDef ext fill:#eee,stroke:#999,color:#333;
    class Weather,Flights,Qdrant,BookingSys ext;
```

## 2. Request lifecycle (sequence)

```mermaid
sequenceDiagram
    actor Employee
    participant UI as Streamlit
    participant GW as API Gateway
    participant O as Orchestrator
    participant W as Weather Agent
    participant F as Flight Agent
    participant P as Policy Agent
    participant G as Guardrails

    Employee->>UI: submit trip request
    UI->>GW: POST /trip-requests (X-Employee-Id)
    GW->>GW: resolve identity -> job_level
    GW->>O: run_trip_planning(request)
    O->>O: check_prompt_injection(destination_city)
    O->>W: geocode + forecast
    W-->>O: weather, geocode
    O->>F: search_flights (route cache checked first)
    F-->>O: candidate fares (sorted by price)
    O->>P: evaluate_fare(cheapest fare)
    P->>P: deterministic threshold check
    P->>P: retrieve_policy_clauses(job_level-scoped)
    P-->>O: ruling + grounded explanation

    alt within policy
        O->>G: auto_approve(trace_id)
    else out of policy, retries remain
        O->>F: re-search at lower cabin class
        F-->>O: new candidate fare
        O->>P: evaluate_fare(new fare)
    else out of policy, no retries left
        O->>G: create_pending_approval(trace_id, approver_role)
    end

    O-->>GW: final state (weather, fares, policy, approval, cost)
    GW-->>UI: response
    UI-->>Employee: display + (if pending) approve/reject buttons
```

## 3. Component responsibilities

| Component | Responsibility | Source |
|---|---|---|
| API Gateway | AuthN (mock OIDC persona), rate limiting, request/response shape | `src/trip_planner/api/main.py`, `auth.py` |
| Orchestrator | LangGraph state machine: dependency order + reflection loop | `src/trip_planner/orchestrator/graph.py` |
| Weather / Flight Agent | Tool-scoped ReAct agents, MCP-backed tools | `src/trip_planner/agents/weather_agent.py`, `flight_agent.py` |
| Policy Agent | Deterministic ruling + grounded LLM explanation, RAG-backed | `src/trip_planner/agents/policy_agent.py` |
| MCP servers | Tool-hosting boundary: trip-lookup (read) vs. booking (the one write action) | `src/trip_planner/mcp_servers/` |
| RAG | Job-level-scoped Qdrant retrieval over the policy corpus | `src/trip_planner/rag/` |
| Guardrails | Allow-list, prompt-injection, groundedness, thresholds, approval gate | `src/trip_planner/guardrails/` |
| Cache | Route cache (exact-match) + semantic cache (policy Q&A) | `src/trip_planner/cache/` |
| Cost ledger | Dual ledger: agent compute $ vs. business fare $ | `src/trip_planner/cost/ledger.py` |
| Audit store | Append-only, PII-redacted, queryable by trace_id | `src/trip_planner/audit/` |
| Observability | Langfuse tracing (no-op without credentials) | `src/trip_planner/observability/` |

See [`HLD.md`](HLD.md) for design rationale and [`LLD.md`](LLD.md) for data
contracts and module-level detail.
