"""Langfuse client — lazily constructed, and a true no-op when
LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY aren't set, so the app runs fine
without a Langfuse account (spec's build-sequencing guidance: observability
is design-for by default, real when credentials are present).

Also fails soft on any Langfuse SDK error (network, API shape change) —
tracing must never be able to break the orchestrator.
"""
from __future__ import annotations

import os
from functools import lru_cache


def langfuse_enabled() -> bool:
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


@lru_cache(maxsize=1)
def get_client():
    """Returns a real Langfuse client, or None if disabled/unavailable.
    Cached — one client per process."""
    if not langfuse_enabled():
        return None
    try:
        from langfuse import Langfuse

        return Langfuse()
    except Exception as exc:  # pragma: no cover - defensive only, never break the app over tracing
        print(f"[observability] Langfuse client unavailable, tracing disabled: {exc}")
        return None
