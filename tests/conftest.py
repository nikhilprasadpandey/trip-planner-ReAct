from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

from trip_planner import config_loader


@pytest.fixture(scope="session", autouse=True)
def _test_isolation_env():
    """Point stateful stores at throwaway/local backends for the whole test
    session, set before anything can lazily connect to the real thing —
    tests must never write into data/audit.db or a real Redis instance,
    even though both are configured for the live app in .env."""
    db_path = Path(tempfile.gettempdir()) / f"trip_planner_test_audit_{uuid.uuid4().hex}.db"
    os.environ["AUDIT_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ.pop("REDIS_URL", None)  # force route_cache's in-memory fallback in tests
    yield
    try:
        db_path.unlink(missing_ok=True)
    except OSError:
        pass


@pytest.fixture(autouse=True)
async def _clear_state():
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
    await route_cache._clear_all()
    yield
    config_loader.clear_cache()
