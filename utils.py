"""Utility helpers for axeos integration."""

from __future__ import annotations

from typing import Any
import re


def normalize_identifier(value: str, fallback: str = "device") -> str:
    """Normalize arbitrary text to a stable identifier using underscores.

    Any non-alphanumeric characters are replaced by "_" and consecutive
    separators are collapsed.
    """
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or fallback


def _first_numeric(mapping: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    """Return first numeric value found in mapping for any candidate key."""
    for key in keys:
        raw = mapping.get(key)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def api_bitaxe_target_temp_c(info: dict[str, Any]) -> float | None:
    """Return Bitaxe target temperature from API payload when available."""
    return _first_numeric(info, ("temptarget", "tempTarget", "temp_target"))


def api_nerdaxe_target_temp_c(info: dict[str, Any]) -> float | None:
    """Return NerdAxe target temperature from API payload when available."""
    value = _first_numeric(
        info,
        (
            "pidTargetTemp",
            "pid_target_temp",
            "targetTemp",
            "target_temp",
        ),
    )
    if value is not None:
        return value

    fans = info.get("fans")
    if isinstance(fans, list) and fans:
        first = fans[0]
        if isinstance(first, dict):
            pid = first.get("pid")
            if isinstance(pid, dict):
                value = _first_numeric(pid, ("targetTemp", "target_temp"))
                if value is not None:
                    return value

    return None
