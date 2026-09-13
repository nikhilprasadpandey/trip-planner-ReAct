"""Exact-match route cache (spec §3.9, §8): a repeated identical route
search must be served from cache with zero additional flight-API/agent
calls — verified here at the cache-storage level.

Runs against the in-memory fallback backend — conftest.py unsets REDIS_URL
for the whole test session, so these never touch a real Redis instance
even though one is configured for the live app."""
from __future__ import annotations

from trip_planner.cache import route_cache
from trip_planner.cache.route_cache import _RedisBackend


async def test_miss_then_hit_returns_stored_result_and_saved_cost():
    assert await route_cache.get("SFO", "AUS", "2026-10-01", "economy") is None

    fares = {"available": True, "fares": [{"carrier": "AA", "price_usd": 400}]}
    await route_cache.set("SFO", "AUS", "2026-10-01", "economy", fares, agent_cost_usd=0.004)

    entry = await route_cache.get("SFO", "AUS", "2026-10-01", "economy")
    assert entry is not None
    assert entry["result"] == fares
    assert entry["agent_cost_saved_usd"] == 0.004


async def test_cache_key_is_case_insensitive_on_airport_codes():
    fares = {"available": True, "fares": []}
    await route_cache.set("sfo", "aus", "2026-10-01", "economy", fares, agent_cost_usd=0.001)
    assert await route_cache.get("SFO", "AUS", "2026-10-01", "economy") is not None


async def test_different_cabin_class_is_a_different_cache_entry():
    await route_cache.set("SFO", "AUS", "2026-10-01", "economy", {"fares": ["e"]}, agent_cost_usd=0.001)
    assert await route_cache.get("SFO", "AUS", "2026-10-01", "business") is None


async def test_different_date_is_a_different_cache_entry():
    await route_cache.set("SFO", "AUS", "2026-10-01", "economy", {"fares": ["a"]}, agent_cost_usd=0.001)
    assert await route_cache.get("SFO", "AUS", "2026-10-02", "economy") is None


async def test_uses_in_memory_backend_when_redis_url_unset(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    route_cache._reset_backend_for_tests()
    assert isinstance(route_cache._get_backend(), route_cache._InMemoryBackend)


async def test_selects_redis_backend_when_redis_url_set(monkeypatch):
    """Doesn't require a real Redis server — only checks that the backend
    selection itself reacts to REDIS_URL; redis.asyncio.from_url() doesn't
    connect eagerly, it just builds a client object."""
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    route_cache._reset_backend_for_tests()
    try:
        assert isinstance(route_cache._get_backend(), route_cache._RedisBackend)
    finally:
        monkeypatch.delenv("REDIS_URL", raising=False)
        route_cache._reset_backend_for_tests()


class _BrokenRedisClient:
    """Stands in for a Redis client that can't reach the server — every
    call raises, the way redis.asyncio does on a real connection failure."""

    async def get(self, key):
        raise ConnectionError("could not connect to Redis")

    async def set(self, key, value, ex=None):
        raise ConnectionError("could not connect to Redis")

    def scan_iter(self, match=None):
        raise ConnectionError("could not connect to Redis")


async def test_redis_backend_degrades_to_a_miss_when_unreachable():
    """Regression: an unreachable Redis instance used to raise straight
    through flight_node, turning a cache problem into a 500 for the whole
    trip request — a cache must never be why a request fails."""
    backend = _RedisBackend(_BrokenRedisClient())

    assert await backend.get("some-key") is None  # never raises
    await backend.set("some-key", "some-value")   # never raises, silently drops the write
