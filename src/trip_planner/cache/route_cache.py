"""Exact-match route cache (spec §3.9): identical origin/destination/date
(+cabin class) searches within a TTL are served from cache instead of
re-hitting the flight API — protects the limited Aviationstack free quota
and is the "second identical search is instant and free" demo beat.

In-process TTLCache (cachetools) — same get/set/ttl shape a Redis-backed
cache would have, so swapping to real Redis later (per the build spec's
guidance to leave Redis design-for-only for the demo) means replacing this
module's storage, not its callers (orchestrator/graph.py's flight_node).

Fares aren't identity-scoped — safe to share across employees, unlike the
policy semantic cache (cache/semantic_cache.py), which is job-level-scoped.
"""
from __future__ import annotations

from typing import TypedDict

from cachetools import TTLCache

_TTL_SECONDS = 600
_MAX_ENTRIES = 1000


class RouteCacheEntry(TypedDict):
    result: dict
    agent_cost_saved_usd: float


_CACHE: TTLCache = TTLCache(maxsize=_MAX_ENTRIES, ttl=_TTL_SECONDS)


def _key(origin: str, destination: str, departure_date: str, cabin_class: str) -> tuple:
    return (origin.upper(), destination.upper(), departure_date, cabin_class)


def get(origin: str, destination: str, departure_date: str, cabin_class: str) -> RouteCacheEntry | None:
    return _CACHE.get(_key(origin, destination, departure_date, cabin_class))


def set(origin: str, destination: str, departure_date: str, cabin_class: str, result: dict, agent_cost_usd: float) -> None:
    _CACHE[_key(origin, destination, departure_date, cabin_class)] = RouteCacheEntry(
        result=result, agent_cost_saved_usd=agent_cost_usd
    )


def _clear_all() -> None:
    """Test helper only."""
    _CACHE.clear()
