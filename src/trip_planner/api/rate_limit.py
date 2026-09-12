"""Rate limiting for the API gateway (spec §2: "API Gateway (authN/authZ,
rate limiting)"). Per-client-IP token bucket via slowapi; generous default
since the real constraint in this system is the flight-provider quota
(protected separately by the route cache, M3), not the gateway itself.
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
