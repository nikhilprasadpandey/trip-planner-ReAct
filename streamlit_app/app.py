"""Streamlit UI v1 (M1) — submit a trip request, watch the plan execute, see
candidate fares + weather. Talks to the FastAPI gateway, never to the
orchestrator/agents/MCP servers directly, matching the architecture in
enterprise_agent_build_spec.md §2.

Persona selection (multi-job-level demo), dual-cost display, and the
audit/trace view are added in M3 once the Policy Agent and cost ledger land.
"""
from __future__ import annotations

import os

import httpx
import streamlit as st

API_GATEWAY_URL = os.environ.get("API_GATEWAY_URL", "http://localhost:8000")

st.set_page_config(page_title="Corporate Travel Planner", page_icon="✈️")
st.title("✈️ Corporate Travel Planner")
st.caption("ReAct multi-agent trip planner — MCP tools, live pricing, weather check.")

with st.form("trip_request"):
    col1, col2 = st.columns(2)
    with col1:
        origin_airport = st.text_input("Origin airport (IATA)", value="SFO", max_chars=3)
        destination_airport = st.text_input("Destination airport (IATA)", value="AUS", max_chars=3)
    with col2:
        destination_city = st.text_input("Destination city", value="Austin, TX")
        departure_date = st.date_input("Departure date")
    cabin_class = st.selectbox("Cabin class", ["economy", "premium_economy", "business", "first"])
    submitted = st.form_submit_button("Plan trip")

if submitted:
    payload = {
        "destination_city": destination_city,
        "origin_airport": origin_airport,
        "destination_airport": destination_airport,
        "departure_date": str(departure_date),
        "cabin_class": cabin_class,
    }
    with st.spinner("Planning your trip — geocoding, checking weather, searching fares..."):
        try:
            resp = httpx.post(f"{API_GATEWAY_URL}/trip-requests", json=payload, timeout=120.0)
            resp.raise_for_status()
            result = resp.json()
        except httpx.HTTPError as exc:
            st.error(f"Request failed: {exc}")
            st.stop()

    st.success(f"Trip planned — trace_id `{result.get('trace_id')}`")

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

    if result.get("status") == "degraded":
        st.warning("This request completed in a degraded state — see errors below.")
        st.json(result.get("errors", []))
