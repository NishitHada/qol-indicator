from __future__ import annotations

from datetime import date, timedelta

from domain.models import FactorResult, FactorStatus
from infra.cache import TTLCache, geo_cache_key
from infra.http_client import get_client

AQI_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

# A year-long window, not a live snapshot: a single clear day scores a location well
# even if it's terrible most of the year (e.g. stubble-burning season), and a single
# bad day does the opposite. Cached for a day since the whole window shifts by at
# most one day between requests - much longer-lived than a live-snapshot read would
# have justified.
_cache = TTLCache(ttl_seconds=86400)

ARCHIVE_LAG_DAYS = 2
WINDOW_DAYS = 365
# A day counts as "bad" once its mean AQI crosses out of Good/Moderate - i.e. into
# Unhealthy-for-Sensitive-Groups or worse.
BAD_DAY_AQI_THRESHOLD = 100
MAX_BAD_DAY_PENALTY = 30.0

# (aqi_lo, aqi_hi, score_at_lo, score_at_hi) - score decreases as AQI increases,
# linearly interpolated within each EPA AQI category band.
_BANDS = [
    (0, 50, 100, 80),
    (50, 100, 80, 60),
    (100, 150, 60, 40),
    (150, 200, 40, 20),
    (200, 300, 20, 10),
    (300, 500, 10, 0),
]


def _score_from_aqi(aqi: float) -> float:
    if aqi <= 0:
        return 100.0
    if aqi >= 500:
        return 0.0
    for lo, hi, score_lo, score_hi in _BANDS:
        if lo <= aqi <= hi:
            frac = (aqi - lo) / (hi - lo)
            return max(0.0, min(100.0, score_lo - frac * (score_lo - score_hi)))
    return 0.0


def _category(aqi: float) -> str:
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Moderate"
    if aqi <= 150:
        return "Unhealthy for Sensitive Groups"
    if aqi <= 200:
        return "Unhealthy"
    if aqi <= 300:
        return "Very Unhealthy"
    return "Hazardous"


def _daily_means(hourly_times: list[str], hourly_aqi: list[float | None]) -> list[float]:
    by_day: dict[str, list[float]] = {}
    for t, v in zip(hourly_times, hourly_aqi, strict=True):
        if v is None:
            continue
        day = t[:10]  # "YYYY-MM-DDTHH:MM" -> "YYYY-MM-DD"
        by_day.setdefault(day, []).append(v)
    return [sum(vals) / len(vals) for vals in by_day.values()]


async def compute(lat: float, lng: float) -> FactorResult:
    # ~11km buckets. Deliberately coarser than the default: this data comes from
    # the CAMS air-quality model, whose own grid is coarser still (25-40km), so a finer cache key
    # just multiplies identical upstream requests - which is what got this
    # endpoint rate-limited (429) in production.
    cache_key = geo_cache_key(lat, lng, precision=1)
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    end_date = date.today() - timedelta(days=ARCHIVE_LAG_DAYS)
    start_date = end_date - timedelta(days=WINDOW_DAYS)

    try:
        client = get_client()
        resp = await client.get(
            AQI_URL,
            params={
                "latitude": lat,
                "longitude": lng,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "hourly": "us_aqi",
                "timezone": "auto",
            },
        )
        resp.raise_for_status()
        hourly = resp.json()["hourly"]
        daily_means = _daily_means(hourly["time"], hourly["us_aqi"])
    except Exception as e:
        return FactorResult(
            key="aqi",
            label="Air quality",
            score=None,
            raw_value=None,
            unit=None,
            status=FactorStatus.ERROR,
            detail=f"Open-Meteo AQI request failed: {e}",
        )

    if not daily_means:
        return FactorResult(
            key="aqi",
            label="Air quality",
            score=None,
            raw_value=None,
            unit=None,
            status=FactorStatus.NOT_FOUND,
            detail="No AQI data available for this location",
        )

    avg_aqi = sum(daily_means) / len(daily_means)
    total_days = len(daily_means)
    bad_days = sum(1 for v in daily_means if v > BAD_DAY_AQI_THRESHOLD)
    bad_fraction = bad_days / total_days

    base_score = _score_from_aqi(avg_aqi)
    penalty = min(MAX_BAD_DAY_PENALTY, bad_fraction * 100.0)
    score = max(0.0, min(100.0, base_score - penalty))

    result = FactorResult(
        key="aqi",
        label="Air quality",
        score=round(score, 1),
        raw_value=round(avg_aqi, 1),
        unit="US AQI avg",
        status=FactorStatus.OK,
        detail=f"{_category(avg_aqi)} avg, {bad_days} bad-air days / {total_days}",
    )
    _cache.set(cache_key, result)
    return result
