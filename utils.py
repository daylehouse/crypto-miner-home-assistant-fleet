"""Utility helpers for axeos integration."""

import re
from typing import Any


def normalize_identifier(value: str, fallback: str = "device") -> str:
    """Normalize arbitrary text to a stable identifier using underscores.

    Any non-alphanumeric characters are replaced by "_" and consecutive
    separators are collapsed.
    """
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or fallback


def bitaxe_mining_active(info: dict[str, Any]) -> bool:
    """Return the best-known Bitaxe mining state from API payload data.

    Prefer explicit state fields when firmware provides them, and fall back
    to hashrate as a compatibility path.
    """
    explicit_active_keys = ("mining_active", "miningActive", "isMiningActive")
    explicit_inactive_keys = ("paused", "isPaused", "shutdown", "isShutdown")

    for key in explicit_active_keys:
        value = info.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)

    for key in explicit_inactive_keys:
        value = info.get(key)
        if isinstance(value, bool):
            return not value
        if isinstance(value, (int, float)):
            return not bool(value)

    hash_rate = info.get("hashRate", 0)
    try:
        return float(hash_rate) > 0
    except (TypeError, ValueError):
        return False
