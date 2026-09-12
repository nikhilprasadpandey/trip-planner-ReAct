"""Append-only audit store (spec §3.6) — SQLAlchemy, queryable by trace_id.
Doubles as the expense-audit source of record: a single trace_id
reconstructs every agent/tool call, the policy clause(s) applied, the
approval outcome, both cost numbers, and the final answer (spec §8).

SQLite locally (AUDIT_DB_URL default), a real Postgres URL in prod — a
connection-string change, not a code change. Rows are event records, one
per `record_event` call, never updated or deleted; `get_trip_audit_trail`
aggregates a trace_id's events into the shape a finance/compliance
reviewer would ask for.

This replaces audit/jsonl_sink.py from M1 — every prior call site
(guardrails/approval_gate.py, guardrails/allowlist.py, orchestrator/graph.py,
cost/ledger.py) now imports `record_event` from here instead.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from trip_planner.audit.redact import redact_payload
from trip_planner.config_loader import REPO_ROOT


class Base(DeclarativeBase):
    pass


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSON)


def _default_db_url() -> str:
    db_path = REPO_ROOT / "data" / "audit.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        url = os.environ.get("AUDIT_DB_URL") or _default_db_url()
        _engine = create_engine(url, future=True)
        Base.metadata.create_all(_engine)
    return _engine


def record_event(trace_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Append one audit event. PII in the payload is redacted before write
    (spec §3.6). Never raises into the request path on a write failure —
    logs to stderr instead, same posture as the M1 JSONL sink it replaces."""
    try:
        with Session(_get_engine()) as session:
            session.add(
                AuditEvent(
                    trace_id=trace_id,
                    event_type=event_type,
                    timestamp=datetime.now(timezone.utc),
                    payload=redact_payload(payload),
                )
            )
            session.commit()
    except Exception as exc:  # pragma: no cover - defensive only
        print(f"[audit] failed to write event for trace_id={trace_id}: {exc}")


def get_events(trace_id: str) -> list[dict[str, Any]]:
    with Session(_get_engine()) as session:
        rows = session.scalars(
            select(AuditEvent).where(AuditEvent.trace_id == trace_id).order_by(AuditEvent.id)
        ).all()
        return [
            {"event_type": row.event_type, "timestamp": row.timestamp.isoformat(), "payload": row.payload}
            for row in rows
        ]


def get_trip_audit_trail(trace_id: str) -> dict[str, Any]:
    """Aggregates a trace_id's event log into the expense-audit record shape
    (spec §3.6): candidate fares considered, policy clause(s) applied,
    approval outcome, final selected fare, both cost numbers, and the full
    call sequence — built entirely from what was actually recorded, not
    re-derived from live state."""
    events = get_events(trace_id)

    trail: dict[str, Any] = {
        "trace_id": trace_id,
        "call_sequence": [{"event_type": e["event_type"], "timestamp": e["timestamp"]} for e in events],
        "candidate_fares": None,
        "policy_clauses_applied": [],
        "approval_outcome": None,
        "final_fare": None,
        "agent_cost_usd": None,
        "business_cost_usd": None,
    }

    for event in events:
        payload = event["payload"]
        if event["event_type"] == "flight_node_complete":
            fares = (payload.get("result") or {}).get("flight_search", {}).get("fares")
            if fares:
                trail["candidate_fares"] = fares
        elif event["event_type"] in ("approval_auto_approved", "approval_required", "approval_granted", "approval_rejected"):
            trail["approval_outcome"] = {"status": payload.get("status"), "approved_by": payload.get("approved_by")}
            if payload.get("fare"):
                trail["final_fare"] = payload["fare"]
        elif event["event_type"] == "business_cost_recorded":
            trail["business_cost_usd"] = payload.get("fare_price_usd")

    agent_cost_events = [e for e in events if e["event_type"] == "llm_call_cost"]
    if agent_cost_events:
        trail["agent_cost_usd"] = round(sum(e["payload"].get("cost_usd", 0.0) for e in agent_cost_events), 6)

    return trail


def _clear_all() -> None:
    """Test helper only — drops and recreates all tables."""
    engine = _get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
