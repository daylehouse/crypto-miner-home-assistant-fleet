"""Utility helpers for axeos integration."""

import re


def normalize_identifier(value: str, fallback: str = "device") -> str:
    """Normalize arbitrary text to a stable identifier using underscores.

    Any non-alphanumeric characters are replaced by "_" and consecutive
    separators are collapsed.
    """
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or fallback
