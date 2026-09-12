"""Loads the YAML config files under `config/` and .env, with env-var overrides.

Single source of truth for locating the repo root and reading
config/guardrails.yaml, config/flight_provider.yaml, config/model_prices.yaml
so every module (tools, agents, cost ledger, guardrails) reads the same
values instead of re-implementing path resolution.
"""
from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# src/trip_planner/config_loader.py -> parents[2] is the repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"

load_dotenv(REPO_ROOT / ".env", override=False)


@functools.lru_cache(maxsize=None)
def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def guardrails_config() -> dict[str, Any]:
    return _load_yaml("guardrails.yaml")


def flight_provider_config() -> dict[str, Any]:
    return _load_yaml("flight_provider.yaml")


def model_prices_config() -> dict[str, Any]:
    return _load_yaml("model_prices.yaml")


def active_flight_provider() -> str:
    """FLIGHT_PROVIDER env var wins over config/flight_provider.yaml."""
    return os.environ.get("FLIGHT_PROVIDER") or flight_provider_config().get("active", "duffel")


def job_level_policy(job_level: str) -> dict[str, Any] | None:
    return guardrails_config().get("job_levels", {}).get(job_level)


def clear_cache() -> None:
    """Test helper — drop cached config reads so a rewritten file is re-read."""
    _load_yaml.cache_clear()
