"""Minimal in-memory TTL cache.

Deliberately not a dependency (no cachetools) — the whole cache is a dict
guarded by wall-clock timestamps. Good enough for a single-process bot; on
Cloud Run each warm instance gets its own cache, which is fine since the
underlying datasets only update roughly monthly.
"""
from __future__ import annotations

import time
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: float):
        self.ttl_seconds = ttl_seconds
        self._store: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: Any, value: Any) -> None:
        self._store[key] = (time.monotonic() + self.ttl_seconds, value)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
