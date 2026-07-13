from __future__ import annotations

from datetime import date, timedelta

from domain.models import FactorResult, FactorStatus
from infra.cache import TTLCache, geo_cache_key
from infra.http_client import get_client

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

_cache = TTLCache(ttl_seconds=86400)

COMFORT_LOW_C = 15.0
COMFORT_HIGH_C = 22.0
DEGRADE_PER_DEGREE = 4.0
EXTREME_HOT_C = 35.0
EXTREME_COLD_C = 0.0
MAX_EXTREME_PENALTY = 50.0
ARCHIVE_LAG_DAYS = 5
WINDOW_DAYS = 365


def _comfort_base(avg_temp: float) -> float:
    if COMFORT_LOW_C <= avg_temp <= COMFORT_HIGH_C:
        return 100.0
    if avg_temp < COMFORT_LOW_C:
        return max(0.0, 100.0 - (COMFORT_LOW_C - avg_temp) * DEGRADE_PER_DEGREE)
    return max(0.0, 100.0 - (avg_temp - COMFORT_HIGH_C) * DEGRADE_PER_DEGREE)


async def compute(lat: float, lng: float) -> FactorResult:
    cache_key = geo_cache_key(lat, lng)
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    end_date = date.today() - timedelta(days=ARCHIVE_LAG_DAYS)
    start_date = end_date - timedelta(days=WINDOW_DAYS)

    try:
        client = get_client()
        resp = await client.get(
            ARCHIVE_URL,
            params={
                "latitude": lat,
                "longitude": lng,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "daily": "temperature_2m_max,temperature_2m_min,temperature_2m_mean",
                "timezone": "auto",
            },
        )
        resp.raise_for_status()
        daily = resp.json()["daily"]
        max_temps = daily["temperature_2m_max"]
        min_temps = daily["temperature_2m_min"]
        mean_temps = daily["temperature_2m_mean"]
    except Exception as e:
        return FactorResult(
            key="temperature",
            label="Temperature",
            score=None,
            raw_value=None,
            unit=None,
            status=FactorStatus.ERROR,
            detail=f"Open-Meteo archive request failed: {e}",
        )

    valid_means = [t for t in mean_temps if t is not None]
    if not valid_means:
        return FactorResult(
            key="temperature",
            label="Temperature",
            score=None,
            raw_value=None,
            unit=None,
            status=FactorStatus.NOT_FOUND,
            detail="No historical temperature data available",
        )

    avg_temp = sum(valid_means) / len(valid_means)
    total_days = len(valid_means)
    extreme_hot_days = sum(1 for t in max_temps if t is not None and t > EXTREME_HOT_C)
    extreme_cold_days = sum(1 for t in min_temps if t is not None and t < EXTREME_COLD_C)
    extreme_days = extreme_hot_days + extreme_cold_days

    base = _comfort_base(avg_temp)
    extreme_fraction = extreme_days / total_days if total_days else 0.0
    penalty = min(MAX_EXTREME_PENALTY, extreme_fraction * 200.0)
    score = max(0.0, min(100.0, base - penalty))

    result = FactorResult(
        key="temperature",
        label="Temperature",
        score=round(score, 1),
        raw_value=round(avg_temp, 1),
        unit="°C avg",
        status=FactorStatus.OK,
        detail=f"{extreme_days} extreme days / {total_days}",
    )
    _cache.set(cache_key, result)
    return result
