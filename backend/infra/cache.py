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


# ~11km. For sources modelled on a grid of several kilometres - air quality,
# temperature, wind - where the answer really is identical across a district and a
# finer key would only multiply identical upstream requests.
REGIONAL_PRECISION = 1

# ~110m. For factors that measure something at street scale. These read the bundled
# datasets rather than the network, so a miss costs microseconds and there is no
# reason to trade accuracy for it.
STREET_PRECISION = 3


def geo_cache_key(lat: float, lng: float, precision: int = 2) -> str:
    """Rounds a point to a cache bucket. The default 2 decimal places is ~1.1km.

    Pick the precision to match what the factor actually resolves, using the constants
    above. The default is too coarse for anything street-scale: at 2 decimal places
    MG Road and Shivajinagar share a bucket, so whichever was scored first answered
    for both - which is exactly how a crowding score of 0 came back as 83.

    It used to be 4 decimal places (~11m) everywhere, which meant essentially every
    distinct click was a cache miss - including for air quality and temperature, whose
    source data is modelled on grids of several kilometres. Caching those per-11m was
    making every click refetch a year of hourly data for no benefit. That is what
    REGIONAL_PRECISION is for; it is not a reason to make everything coarse.
    """
    return f"{round(lat, precision)},{round(lng, precision)}"
