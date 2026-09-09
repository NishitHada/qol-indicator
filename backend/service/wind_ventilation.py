from __future__ import annotations

import math
from datetime import date, timedelta

from domain.models import FactorResult, FactorStatus
from infra.cache import TTLCache, geo_cache_key
from infra.http_client import get_client
from service import local_climate

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

_cache = TTLCache(ttl_seconds=86400)

KEY = "wind_ventilation"
LABEL = "Wind / cross-ventilation"

ARCHIVE_LAG_DAYS = 5
WINDOW_DAYS = 365

# Daily peak wind, in km/h, at which a home ventilates fully on its own. Below this the
# score falls off proportionally; above it there is nothing more to gain, so a gale
# does not score higher than a steady breeze.
GOOD_WIND_KMH = 18.0
# Eight compass sectors - the resolution at which "the wind comes from a different
# side today" is a real statement about a flat rather than instrument noise.
DIRECTION_SECTORS = 8

SPEED_WEIGHT = 0.7
VARIETY_WEIGHT = 0.3


def _speed_component(mean_peak_kmh: float) -> float:
    return max(0.0, min(100.0, 100.0 * mean_peak_kmh / GOOD_WIND_KMH))


def _direction_variety(directions: list[float]) -> float:
    """How evenly the year's wind is spread across the eight compass sectors, 0-100.

    This is the half of ventilation that average wind speed cannot express. Cross-
    ventilation needs air to enter one side of a flat and leave the other, so it
    depends on the *orientation* of the wind as much as its strength. A location whose
    wind arrives from one sector all year ventilates only the flats that happen to face
    it; Bangalore's own monsoon reversal, westerlies in June and easterlies in
    November, is why most of the city scores well here.

    Shannon entropy over the sector histogram, normalised by its maximum, so a perfectly
    even spread is 100 and a single-sector year is 0.
    """
    counts = [0] * DIRECTION_SECTORS
    total = 0
    for deg in directions:
        if deg is None:
            continue
        counts[int((deg % 360) / (360 / DIRECTION_SECTORS))] += 1
        total += 1
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in counts:
        if count:
            p = count / total
            entropy -= p * math.log(p)
    return 100.0 * entropy / math.log(DIRECTION_SECTORS)


async def _fetch_series(lat: float, lng: float) -> tuple[list, list]:
    end_date = date.today() - timedelta(days=ARCHIVE_LAG_DAYS)
    start_date = end_date - timedelta(days=WINDOW_DAYS)
    resp = await get_client().get(
        ARCHIVE_URL,
        params={
            "latitude": lat,
            "longitude": lng,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "daily": "wind_speed_10m_max,wind_direction_10m_dominant",
            "timezone": "auto",
        },
    )
    resp.raise_for_status()
    daily = resp.json()["daily"]
    return daily["wind_speed_10m_max"], daily["wind_direction_10m_dominant"]


async def compute(lat: float, lng: float) -> FactorResult:
    # ~11km buckets, matching temperature: this reads the same ERA5 reanalysis, whose
    # own grid is coarser still, so a finer key would only multiply identical requests.
    cache_key = geo_cache_key(lat, lng, precision=1)
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    # Bundled first, exactly as temperature does - Open-Meteo's archive rate-limits
    # Render's shared outbound IP, so a live call would leave this permanently
    # unverified in production.
    bundled = local_climate.wind_series(lat, lng)
    if bundled is not None:
        speeds, directions = bundled
    else:
        try:
            speeds, directions = await _fetch_series(lat, lng)
        except Exception as e:
            return FactorResult(
                key=KEY,
                label=LABEL,
                score=None,
                raw_value=None,
                unit=None,
                status=FactorStatus.ERROR,
                detail=f"Open-Meteo archive request failed: {e}",
            )

    valid_speeds = [s for s in speeds if s is not None]
    if not valid_speeds:
        return FactorResult(
            key=KEY,
            label=LABEL,
            score=None,
            raw_value=None,
            unit=None,
            status=FactorStatus.NOT_FOUND,
            detail="No historical wind data available",
        )

    mean_peak = sum(valid_speeds) / len(valid_speeds)
    speed_score = _speed_component(mean_peak)
    variety_score = _direction_variety(directions)
    score = SPEED_WEIGHT * speed_score + VARIETY_WEIGHT * variety_score

    # This is a regional reading, not a site one. ERA5 resolves ~25km cells, so it
    # describes the wind arriving at the neighbourhood and cannot see whether the
    # building next door blocks it - which is why the label says wind, and the detail
    # says what was actually measured.
    result = FactorResult(
        key=KEY,
        label=LABEL,
        score=round(max(0.0, min(100.0, score)), 1),
        raw_value=round(mean_peak, 1),
        unit="km/h avg daily peak",
        status=FactorStatus.OK,
        source="open-meteo",
        detail=f"{round(mean_peak, 1)} km/h avg peak, direction variety {round(variety_score)}/100",
    )
    _cache.set(cache_key, result)
    return result
