# Build Specification: Corporate Travel Planner & Policy-Compliance Agent
### (ReAct multi-agent, MCP, live flight pricing, Pinecone policy RAG, guardrails, audit, cost, auth)

Use this document as the prompt/spec for the build phase. It replaces the
generic healthcare-anchored version with a concrete use case: an employee
asks for a trip, the system finds live flights, checks weather, checks the
fare against corporate travel policy, and routes anything out-of-policy for
human approval before "booking" (booking action is stubbed for the demo).

---

## 1. Role & Objective

You are building a production-minded agentic AI platform for a corporate
travel use case, in an organization with real travel-policy compliance and
expense-audit requirements (this maps directly to the client's hospitality/
travel engagements). Every requirement below is a hard requirement unless
marked "(optional/v2)". The system must survive a FinOps review (real
dollar cost, not just LLM token cost) and an expense-audit review, not just
a functional demo review.

---

## 2. System Overview

```
Employee (authenticated, role-scoped)
  -> API Gateway (authN/authZ, rate limiting)
    -> Orchestrator Agent (ReAct, native tool calling, planning)
        -> Flight Agent   -> MCP -> Aviationstack (live) / Duffel (test mode)
        -> Weather Agent  -> MCP -> Nominatim (geocode) + Open-Meteo (forecast)
        -> Policy Agent   -> Pinecone retriever -> corporate travel policy corpus
    -> Guardrails layer (pre- and post-LLM-call; approval gate on out-of-policy fares)
    -> Cache layer (route-search cache + semantic policy-answer cache)
    -> Observability layer (Langfuse tracing, dual cost tracking)
    -> Audit log store (immutable, queryable) -> feeds expense-audit trail
```

Every request carries one `trace_id`, propagated through every agent, tool
call, cache hit/miss, guardrail check, and LLM call, correlated in Langfuse
and the audit log by that same id. For this use case, `trace_id` doubles as
the natural key for an expense-audit record: "what did the agent find, what
did policy say, who approved it."

### 2.1 API landscape note (checked at spec time, re-verify before build)
Amadeus's Self-Service sandbox was decommissioned July 17, 2026 - it is no
longer a viable free flight-pricing source. Use:
- **Aviationstack** (live, ~100 free requests) for the actual demo walkthrough
- **Duffel test mode** (sandbox data, real API shape) for development and
  rehearsal, so the limited live quota isn't burned during iteration
- Design the Flight Agent's tool interface so the underlying provider is
  swappable (same pattern as the LLM adapter) - whichever flight API is
  free/available shifts fast in this space, don't hardcode against one.

---

## 3. Functional Requirements

### 3.1 Multi-agent ReAct core
- **Orchestrator Agent**: decomposes "plan my trip to Austin next week" into
  an ordered plan - geocode -> weather -> flight search -> policy check -
  respecting dependencies (can't check weather before geocoding city name;
  can't check policy before a fare exists to check). This is the Planning
  pattern layered on top of ReAct, not just single-tool ReAct.
- **Flight Agent**: native tool-calling ReAct agent scoped to flight-search
  tools only (Aviationstack/Duffel via MCP). Returns candidate fares with
  carrier, price, cabin class, and fare rules.
- **Weather Agent**: unchanged from the existing prototype (Nominatim +
  Open-Meteo via MCP) - reused as-is, proving the "swap the domain, reuse
  the specialist" value of the architecture.
- **Policy Agent**: retrieves relevant travel-policy clauses from Pinecone
  (see 3.3), evaluates a specific fare against them, and - this is the
  Reflection pattern - if the first candidate fare is out-of-policy, it
  re-queries the Flight Agent (via the orchestrator) for a cheaper or
  lower-cabin-class alternative before finalizing, rather than simply
  reporting a violation and stopping.
- Every agent's tool set is explicitly allow-listed at construction time.

### 3.2 MCP integration
- Two MCP servers: (a) the existing free-tools server (geocode, weather),
  extended with a `search_flights` tool wrapping Aviationstack/Duffel; (b) a
  stub "booking system" MCP server exposing a single mutating tool,
  `book_flight`, that is never called without passing the approval guardrail
  (3.4) - this is the one write action in the whole system, and it exists
  specifically to exercise the human-in-the-loop guardrail requirement.
- MCP server health-checks and graceful degradation (unchanged from the
  general spec): if the flight-pricing MCP server is down or the free quota
  is exhausted, the Flight Agent returns a clear "pricing unavailable"
  observation rather than hanging or crashing the orchestrator.

### 3.3 Vector DB / RAG (Pinecone) - corporate travel policy
- Corpus: a synthetic corporate travel policy document - cabin-class
  eligibility by job level, per-route spend caps, pre-approval thresholds,
  preferred-carrier rules, advance-booking requirements.
- Ingestion pipeline: chunk by policy section, embed, upsert with metadata
  (section id, job-level applicability, last-updated date).
- **Namespace/metadata scoping by job level**: a manager-level employee's
  query should surface the manager-tier spend cap, not the individual-
  contributor tier - same clause corpus, filtered results. This is the
  single most convincing demo moment from the original architecture
  discussion, now made concrete: two employees, same route, different
  (correctly scoped) policy answer and different approval outcome.
- Retriever tool exposed only to the Policy Agent, returning top-k clauses
  with citations (section id) so a "this fare is out of policy" answer can
  be traced back to the exact clause, not asserted from the model's own
  reasoning.

### 3.4 Guardrails
- **Approval gate (the core guardrail for this use case)**: any fare
  exceeding the applicable policy threshold (from 3.3) blocks the
  `book_flight` tool call and instead emits an approval request (stubbed as
  a structured record for the demo - "requires approval from: <manager
  role>"). The agent must not call the mutating tool until an approval
  record exists for that `trace_id`.
- **Input guardrails**: prompt-injection detection on user input and on any
  retrieved policy text or tool observation fed back into an LLM call.
- **Output guardrails**: the Policy Agent's answer must be grounded in a
  retrieved clause (groundedness check) - it should not assert a policy
  rule that wasn't actually retrieved.
- **Tool-call guardrails**: allow-list enforcement per agent (defense in
  depth on top of 3.1); `book_flight` specifically requires the approval
  record above regardless of which agent attempts to call it.
- Guardrail policy (thresholds, which roles approve which tiers) lives in a
  config file, not hardcoded logic, so travel/finance ops can adjust
  spend caps without a code deploy.

### 3.5 Cost tracking - dual-ledger
This use case has two cost dimensions that must be tracked and reported
separately, and this distinction is worth calling out explicitly in the
demo:
- **Agent operating cost**: LLM tokens (input/output/cached) per call, per
  agent, aggregated per trip-planning request - the FinOps-on-the-AI-system
  number.
- **Business cost being evaluated**: the actual flight fare(s) considered
  and the one ultimately selected - the FinOps-on-the-business-process
  number (this is the number a travel manager actually cares about).
- Both numbers attach to the same `trace_id` and appear together in the
  audit record, so "this trip cost $412 in airfare and $0.03 in agent
  compute to plan" is a single reportable line.
- Budget/threshold alerting on the agent-operating-cost side (existing
  general requirement); spend-cap alerting on the business-cost side is
  handled by the Policy Agent/guardrail (3.4), not duplicated here.

### 3.6 Audit readiness - expense-audit trail
- Immutable, append-only record per request: `trace_id`, employee id, job
  level, requested route/dates, candidate fares considered, policy
  clause(s) applied, approval outcome (auto-approved / pending / approved-
  by-whom), final selected fare, both cost numbers from 3.5, and full
  agent/tool call sequence.
- This record is, by construction, what an internal-audit or expense-
  compliance reviewer would ask for - the spec doesn't need a separate
  "audit view," the operational record already is the audit artifact.
- PII (employee id beyond what's needed, personal travel preferences)
  redacted/tokenized before write, consistent with the general spec.
- Retention and access control unchanged from the general spec (define who
  in finance/compliance can query this store and for how long).

### 3.7 Auth
- Employee identity via enterprise IdP (OIDC/OAuth2) - unchanged from the
  general spec.
- **RBAC drives two things concretely in this use case**: (a) which cabin
  class / spend tier applies when the Policy Agent evaluates a fare, and
  (b) who the approval request routes to when a fare exceeds that tier.
  Both are re-checked at the Policy Agent's retrieval call (job-level
  metadata filter into Pinecone), not just at the API gateway.
- Service-to-service auth for both MCP servers (flight-pricing and the
  stub booking system) - the booking-system connection in particular
  should be treated as higher-trust/higher-scrutiny given it's the one
  mutating action in the system.

### 3.8 Langfuse integration
- One trace per trip-planning request; nested spans per agent (Orchestrator,
  Flight, Weather, Policy) and per tool call, tagged with `trace_id`,
  employee job-level (not raw identity), and both cost numbers from 3.5.
- Guardrail events (approval required, approval granted, groundedness
  check failed) logged as span-level metadata so "how often do fares come
  back out-of-policy" becomes a queryable trend, not just an anecdote from
  the demo.
- A sample of Policy Agent answers scored for groundedness against the
  retrieved Pinecone clauses, on the schedule defined in the general spec.

### 3.9 Caching
- **Exact-match route cache**: identical origin/destination/date searches
  within a short TTL served from cache rather than re-hitting the flight
  API - directly protects the limited Aviationstack free quota, and is an
  easy, visible "second identical search is instant and free" demo beat.
- **Semantic cache** for Policy Agent answers (e.g., two differently-worded
  questions about the same spend-cap clause) - same invalidation rule as
  the general spec: invalidate when the underlying policy doc changes.
- Cache keys scoped by job level for policy answers (a cached answer for
  one tier must never be served to another tier), and by route+date for
  flight-search results (fares aren't identity-scoped, safe to share
  across employees).
- Every cache hit still logged (audit + Langfuse) with the agent-operating-
  cost it saved recorded for FinOps reporting, per the general spec.

---

## 4. Non-Functional Requirements
(Unchanged from the general spec - reliability/retries on the flight API in
particular given its limited free quota and the Amadeus-shutdown precedent;
scalability; latency targets per request type; multi-tenancy by job level
and/or business unit; environment separation; testing including an offline
dry-run extended to cover the approval-gate and dual-cost-ledger paths.)

---

## 5. Tech Stack

- LLM: Anthropic Claude, native tool calling, existing adapter pattern.
- Orchestration: existing `Agent`/`Orchestrator` classes, extended with a
  Policy Agent and the planning/reflection behavior in 3.1.
- Flight pricing: Aviationstack (live, demo) behind a provider-swappable
  interface; Duffel (test mode) for development.
- Weather/geocoding: Nominatim + Open-Meteo, unchanged, reused as-is.
- Vector DB: Pinecone, corporate travel-policy corpus.
- Cache: Redis (exact-match route cache) + semantic layer for policy Q&A.
- Observability: Langfuse.
- Auth: OIDC client against enterprise IdP; RBAC middleware keyed on job
  level.
- Audit store: append-only Postgres (or equivalent), queryable by
  `trace_id`, doubling as the expense-audit source of record.
- Secrets: Vault or cloud-native KMS/secrets manager.

---

## 6. Build Sequencing (three passes, as scoped in discussion)

**Pass 1 - core flow**: Orchestrator + Flight Agent (Aviationstack/Duffel
via MCP) + Weather Agent (reused as-is). Basic structured-log audit trail
(JSONL is fine for this pass). Proves the architecture extends to a new
domain with minimal new code.

**Pass 2 - the enterprise story**: Policy Agent with Pinecone RAG over the
synthetic travel-policy corpus; the approval-gate guardrail in front of
`book_flight`; Langfuse tracing wired in for live narration during a demo.

**Pass 3 - the production-minded close**: dual cost-ledger surfaced live
(agent cost vs. fare cost); route-cache hit demonstrated live (search the
same route twice); two synthetic employees at different job levels asking
the same question and getting different (correctly scoped) policy answers
and approval outcomes.

Leave real IdP/SSO, Redis, and Vault out of the live demo itself (design-
for, not proven live), consistent with the general spec's guidance.

---

## 7. Deliverables Expected From the Build Phase

1. Architecture diagram reflecting the four agents, two MCP servers, and
   Pinecone policy retriever above.
2. Code for: Flight Agent + provider-swappable flight-search tool, Policy
   Agent + Pinecone ingestion/retrieval pipeline, approval-gate guardrail,
   dual cost-ledger module, Langfuse instrumentation, route/semantic cache
   layer, auth/RBAC middleware keyed on job level, audit logging module -
   each independently testable, wired into the existing `Agent`/
   `Orchestrator` classes.
3. Config files: guardrail policy YAML (spend caps and approval routing by
   job level), flight-provider config (Aviationstack vs. Duffel toggle),
   per-model price table.
4. Extended offline dry-run test covering: happy path, an out-of-policy
   fare triggering the approval gate, a cache hit on a repeated route
   search, and two job-level personas receiving different policy answers.
5. A short "how to audit a trip request" runbook: given a `trace_id`, pull
   the full expense-audit record (fares considered, policy applied,
   approval outcome, both cost numbers) and cross-check against Langfuse.

## 8. Acceptance Criteria

- A single `trace_id` reconstructs: every agent/tool call, the policy
  clause(s) applied, the approval outcome, both cost numbers, and the
  final answer - matching between the audit store and Langfuse.
- `book_flight` is never called without a corresponding approval record
  for that `trace_id`.
- A repeated identical route search is served from cache with zero
  additional flight-API calls and zero additional agent-operating cost
  logged (beyond the recorded savings).
- Two employees at different job levels asking the identical question
  receive policy answers and approval outcomes correctly scoped to their
  own tier - never leaking another tier's threshold as their own.
- If the flight-pricing provider is unavailable or quota-exhausted, the
  Flight Agent degrades gracefully with a clear message rather than
  hanging or crashing the orchestrator.
