from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

from trip_planner import config_loader


@pytest.fixture(scope="session", autouse=True)
def _test_audit_db():
    """Point the audit store at a throwaway SQLite file for the whole test
    session, set before anything can lazily create the real engine — tests
    must never write into data/audit.db."""
    db_path = Path(tempfile.gettempdir()) / f"trip_planner_test_audit_{uuid.uuid4().hex}.db"
    os.environ["AUDIT_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    yield
    try:
        db_path.unlink(missing_ok=True)
    except OSError:
        pass


@pytest.fixture(autouse=True)
def _clear_state():
    """Config is lru_cache'd for the app's lifetime; the audit store, cost
    ledger, approval records, and caches are module-level in-memory/DB state
    — all need a clean slate between tests."""
    from trip_planner.audit import store as audit_store
    from trip_planner.cache import route_cache
    from trip_planner.cost import ledger
    from trip_planner.guardrails import approval_gate

    config_loader.clear_cache()
    audit_store._clear_all()
    ledger._clear_all()
    approval_gate._clear_all()
    route_cache._clear_all()
    yield
    config_loader.clear_cache()
