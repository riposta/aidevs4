"""Simple in-memory data store for passing large payloads between tools without polluting LLM context."""

from __future__ import annotations

from core.log import get_logger

log = get_logger("store")

_data: dict[str, str] = {}


def store_put(key: str, value: str) -> str:
    """Store a value under a key. Returns a short reference string."""
    _data[key] = value
    size = len(value)
    log.info("Stored '%s' (%d chars)", key, size)
    return f"_store:{key}"


def store_get(key: str) -> str | None:
    """Retrieve a value by key."""
    return _data.get(key)


def store_clear() -> None:
    """Clear all stored data."""
    _data.clear()
