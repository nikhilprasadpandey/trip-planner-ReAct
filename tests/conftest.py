from __future__ import annotations

import pytest

from trip_planner import config_loader


@pytest.fixture(autouse=True)
def _clear_config_cache():
    """Config is lru_cache'd for the app's lifetime; tests that monkeypatch
    env vars (e.g. FLIGHT_PROVIDER) need a clean read each time."""
    config_loader.clear_cache()
    yield
    config_loader.clear_cache()
