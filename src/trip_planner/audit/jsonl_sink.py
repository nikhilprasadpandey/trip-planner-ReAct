"""M1 placeholder audit sink — append-only JSONL, keyed by trace_id.

Superseded in M3 by audit/store.py (SQLAlchemy, queryable, the real
expense-audit source of record). Kept intentionally dumb: one JSON object
per line, flushed immediately, so nothing here can lose an event.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trip_planner.config_loader import REPO_ROOT

_DEFAULT_PATH = REPO_ROOT / "data" / "audit_events.jsonl"


def _sink_path() -> Path:
    path = Path(os.environ.get("AUDIT_JSONL_PATH", str(_DEFAULT_PATH)))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def record_event(trace_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Append one audit event. Never raises on a write failure into the
    request path in M1 — logs to stderr instead, since JSONL is a
    placeholder and must not be allowed to crash the orchestrator."""
    entry = {
        "trace_id": trace_id,
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    try:
        with _sink_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError as exc:  # pragma: no cover - defensive only
        print(f"[audit] failed to write event for trace_id={trace_id}: {exc}")
