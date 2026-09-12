"""Exact-match route cache (spec §3.9): identical origin/destination/date
(+cabin class) searches within a TTL are served from cache instead of
re-hitting the flight API — protects the limited Aviationstack free quota
and is the "second identical search is instant and free" demo beat.

Backed by real Redis when REDIS_URL is set, with a transparent in-process
(cachetools) fallback when it isn't — same async get/set shape either way,
so callers (orchestrator/graph.py's flight_node) never know which backend
is active. This is the swap the module's own docstring used to promise
("same get/set/ttl shape a Redis-backed cache would have") — now made
real rather than just designed-for.

Fares aren't identity-scoped — safe to share across employees, unlike the
policy semantic cache (cache/semantic_cache.py), which is job-level-scoped
and stays in-process (similarity search over embeddings doesn't map onto a
plain Redis GET/SET the way an exact-match lookup does).
"""
from __future__ import annotations

import json
import os
from typing import Protocol, TypedDict

from cachetools import TTLCache

_TTL_SECONDS = 600
_MAX_ENTRIES = 1000  # in-memory fallback only — Redis has no such cap here
_KEY_PREFIX = "trip_planner:route_cache:"


class RouteCacheEntry(TypedDict):
    result: dict
    agent_cost_saved_usd: float


class _Backend(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str) -> None: ...
    async def clear(self) -> None: ...


class _InMemoryBackend:
    """Fallback used when REDIS_URL isn't configured — single-process only,
    lost on restart. Fine for local dev; not for a multi-instance deploy."""

    def __init__(self) -> None:
        self._cache: TTLCache = TTLCache(maxsize=_MAX_ENTRIES, ttl=_TTL_SECONDS)

    async def get(self, key: str) -> str | None:
        return self._cache.get(key)

    async def set(self, key: str, value: str) -> None:
        self._cache[key] = value

    async def clear(self) -> None:
        self._cache.clear()


class _RedisBackend:
    def __init__(self, client) -> None:
        self._client = client

    async def get(self, key: str) -> str | None:
        value = await self._client.get(key)
        if value is None:
            return None
        return value.decode("utf-8") if isinstance(value, bytes) else value

    async def set(self, key: str, value: str) -> None:
        await self._client.set(key, value, ex=_TTL_SECONDS)

    async def clear(self) -> None:
        # Scoped to this cache's own key prefix — never flush the whole
        # Redis logical DB, which may be shared with other uses.
        async for k in self._client.scan_iter(match=f"{_KEY_PREFIX}*"):
            await self._client.delete(k)


_backend: _Backend | None = None


def _get_backend() -> _Backend:
    global _backend
    if _backend is None:
        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            import redis.asyncio as redis  # local import: optional dependency, only needed when configured

            _backend = _RedisBackend(redis.from_url(redis_url))
        else:
            _backend = _InMemoryBackend()
    return _backend


def _key(origin: str, destination: str, departure_date: str, cabin_class: str) -> str:
    return f"{_KEY_PREFIX}{origin.upper()}:{destination.upper()}:{departure_date}:{cabin_class}"


async def get(origin: str, destination: str, departure_date: str, cabin_class: str) -> RouteCacheEntry | None:
    raw = await _get_backend().get(_key(origin, destination, departure_date, cabin_class))
    if raw is None:
        return None
    return json.loads(raw)


async def set(origin: str, destination: str, departure_date: str, cabin_class: str, result: dict, agent_cost_usd: float) -> None:
    entry = RouteCacheEntry(result=result, agent_cost_saved_usd=agent_cost_usd)
    await _get_backend().set(_key(origin, destination, departure_date, cabin_class), json.dumps(entry))


async def _clear_all() -> None:
    """Test helper only."""
    await _get_backend().clear()


def _reset_backend_for_tests() -> None:
    """Test helper only — drop the cached backend so the next call picks up
    a changed REDIS_URL (e.g. monkeypatched in a specific test)."""
    global _backend
    _backend = None
