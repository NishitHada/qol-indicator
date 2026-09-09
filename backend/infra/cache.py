from __future__ import annotations

import time
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: float):
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic() + self._ttl, value)


def geo_cache_key(lat: float, lng: float, precision: int = 2) -> str:
    """Rounds a point to a cache bucket. The default 2 decimal places is ~1.1km.

    This used to be 4 decimal places (~11m), which meant essentially every distinct
    click was a cache miss - including for air quality and temperature, whose source
    data is modelled on grids of several kilometres and is genuinely identical across
    a whole district. Caching those per-11m was making every click refetch a year of
    hourly data for no benefit.
    """
    return f"{round(lat, precision)},{round(lng, precision)}"
