"""Streamlit UI (M1-M3) — submit a trip request, watch the plan execute,
see weather/fares/policy/approval, the dual cost ledger, and a cache-hit
indicator on a repeated search. Talks to the FastAPI gateway, never to the
orchestrator/agents/MCP servers directly, matching enterprise_agent_build_spec.md §2.

Persona selector in the sidebar is the M3 acceptance-criteria demo: two
employees at different job levels, same route/date, different (correctly
scoped) policy answer and approval outcome (spec §8).
"""
from __future__ import annotations

import os

import httpx
import streamlit as st

API_GATEWAY_URL = os.environ.get("API_GATEWAY_URL", "http://localhost:8000")

# Mirrors src/trip_planner/api/auth.py's mock personas.
PERSONAS = {
    "Individual Contributor (employee-ic-001)": "employee-ic-001",
    "Manager (employee-mgr-001)": "employee-mgr-001",
    "Director (employee-dir-001)": "employee-dir-001",
}

st.set_page_config(page_title="Corporate Travel Planner", page_icon="✈️")
st.title("✈️ Corporate Travel Planner")
st.caption("ReAct multi-agent trip planner — MCP tools, live pricing, weather check, policy compliance.")

with st.sidebar:
    st.subheader("👤 Acting as")
    persona_label = st.selectbox("Employee", list(PERSONAS.keys()))
    employee_id = PERSONAS[persona_label]
    st.caption("Switch personas and replay the same request to see the job-level-scoped policy/approval outcome diverge.")

    st.divider()
    st.subheader("📋 Ask a policy question")
    policy_query = st.text_input("Question", placeholder="What's my spend cap on a domestic flight?")
    if st.button("Ask") and policy_query:
        with st.spinner("Checking policy..."):
            try:
                resp = httpx.post(
                    f"{API_GATEWAY_URL}/policy-questions",
                    json={"query": policy_query},
                    headers={"X-Employee-Id": employee_id},
                    timeout=60.0,
                )
                resp.raise_for_status()
                qa = resp.json()
            except httpx.HTTPError as exc:
                st.error(f"Request failed: {exc}")
                qa = None
        if qa:
            st.write(qa.get("answer", ""))
            st.caption("⚡ Served from semantic cache" if qa.get("cache_hit") else "🧠 Computed fresh")
            if not qa.get("grounded", True):
                st.caption("⚠️ Not grounded in a retrieved clause — treat with caution.")

_headers = {"X-Employee-Id": employee_id}

with st.form("trip_request"):
    col1, col2 = st.columns(2)
    with col1:
        origin_airport = st.text_input("Origin airport (IATA)", value="SFO", max_chars=3)
        destination_airport = st.text_input("Destination airport (IATA)", value="AUS", max_chars=3)
    with col2:
        destination_city = st.text_input("Destination city", value="Austin, TX")
        departure_date = st.date_input("Departure date")
    col3, col4 = st.columns(2)
    with col3:
        cabin_class = st.selectbox("Cabin class", ["economy", "premium_economy", "business", "first"])
    with col4:
        is_international = st.checkbox("International route")
    submitted = st.form_submit_button("Plan trip")

if submitted:
    payload = {
        "destination_city": destination_city,
        "origin_airport": origin_airport,
        "destination_airport": destination_airport,
        "departure_date": str(departure_date),
        "cabin_class": cabin_class,
        "is_international": is_international,
    }
    with st.spinner("Planning your trip — geocoding, checking weather, searching fares, checking policy..."):
        try:
            resp = httpx.post(f"{API_GATEWAY_URL}/trip-requests", json=payload, headers=_headers, timeout=120.0)
            resp.raise_for_status()
            result = resp.json()
        except httpx.HTTPError as exc:
            st.error(f"Request failed: {exc}")
            st.stop()

    trace_id = result.get("trace_id")
    st.success(f"Trip planned as **{persona_label}** — trace_id `{trace_id}`")
    st.session_state["last_trace_id"] = trace_id

    weather = result.get("weather")
    if weather:
        st.subheader("🌤️ Weather forecast")
        st.dataframe(weather.get("forecast", []), use_container_width=True)
    else:
        st.info("No weather data returned.")

    flights = result.get("flight_search")
    st.subheader("🛫 Candidate fares")
    if flights and flights.get("available"):
        st.dataframe(flights.get("fares", []), use_container_width=True)
        if any(f.get("price_is_estimated") for f in flights.get("fares", [])):
            st.caption("⚠️ Prices marked estimated come from a provider with no native fare-pricing data.")
    else:
        reason = (flights or {}).get("reason", "unknown")
        st.warning(f"Pricing unavailable: {reason}")

    policy = result.get("policy_evaluation")
    approval = result.get("approval") or {}
    if policy and not policy.get("skipped"):
        st.subheader("📋 Policy evaluation")
        threshold = policy.get("threshold", {})
        if threshold.get("within_policy"):
            st.success(f"Within policy — cap ${threshold.get('cap_usd', 0):.2f} for {persona_label.split(' (')[0]}.")
        else:
            st.warning(f"Out of policy — cap ${threshold.get('cap_usd', 0):.2f} for {persona_label.split(' (')[0]}.")
        st.caption(policy.get("explanation", ""))
        if not policy.get("grounded", True):
            st.caption("⚠️ Explanation did not cite a retrieved policy clause — treat the ruling above (not the LLM's prose) as authoritative.")

    if approval:
        status = approval.get("status")
        if status == "auto_approved":
            st.success("✅ Auto-approved — within policy.")
        elif status == "pending":
            st.warning(f"⏳ Pending approval from: {approval.get('approver_role')}")
            st.caption("Grant/reject below (demo only — real RBAC on who may approve is a later pass).")
            approver_id = st.text_input("Approving as (employee id)", value="employee-mgr-001", key=f"approver-{trace_id}")
            gcol, rcol = st.columns(2)
            if gcol.button("Grant approval", key=f"grant-{trace_id}"):
                httpx.post(f"{API_GATEWAY_URL}/approvals/{trace_id}/grant", json={"approved_by": approver_id}, timeout=30.0)
                st.rerun()
            if rcol.button("Reject", key=f"reject-{trace_id}"):
                httpx.post(f"{API_GATEWAY_URL}/approvals/{trace_id}/reject", json={"approved_by": approver_id}, timeout=30.0)
                st.rerun()
        elif status == "approved":
            st.success(f"✅ Approved by {approval.get('approved_by')}.")
        elif status == "not_applicable":
            st.info("No fare was available to evaluate against policy.")

    if approval.get("status") in ("auto_approved", "approved"):
        if st.button("Book this fare (stub)", key=f"book-{trace_id}"):
            book_resp = httpx.post(f"{API_GATEWAY_URL}/trip-requests/{trace_id}/book", timeout=30.0)
            book_result = book_resp.json()
            if book_result.get("booked"):
                st.success(f"✈️ Booked — confirmation {book_result['confirmation_id']} (stub, no real reservation made).")
            else:
                st.error(f"Booking blocked: {book_result.get('reason')}")

    cost = result.get("cost")
    if cost:
        st.subheader("💰 Dual cost ledger")
        c1, c2 = st.columns(2)
        c1.metric("Agent compute cost", f"${cost.get('agent_cost_usd', 0):.4f}")
        c2.metric(
            "Business (fare) cost",
            f"${cost['business_cost_usd']:.2f}" if cost.get("business_cost_usd") else "— (not yet approved)",
        )

    if result.get("status") == "degraded":
        st.warning("This request completed in a degraded state — see errors below.")
        st.json(result.get("errors", []))

st.divider()
st.caption(
    "Tip: submit the same origin/destination/date twice in a row — the second flight search should be "
    "noticeably faster (route cache hit, zero additional agent cost logged)."
)
