from __future__ import annotations

from domain.models import FactorResult, FactorStatus
from infra.cache import TTLCache, geo_cache_key
from infra.http_client import get_client

AQI_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

_cache = TTLCache(ttl_seconds=600)

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


async def compute(lat: float, lng: float) -> FactorResult:
    cache_key = geo_cache_key(lat, lng)
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        client = get_client()
        resp = await client.get(
            AQI_URL,
            params={"latitude": lat, "longitude": lng, "current": "us_aqi", "timezone": "auto"},
        )
        resp.raise_for_status()
        data = resp.json()
        aqi = data["current"]["us_aqi"]
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

    if aqi is None:
        return FactorResult(
            key="aqi",
            label="Air quality",
            score=None,
            raw_value=None,
            unit=None,
            status=FactorStatus.NOT_FOUND,
            detail="No AQI data available for this location",
        )

    score = _score_from_aqi(aqi)
    result = FactorResult(
        key="aqi",
        label="Air quality",
        score=round(score, 1),
        raw_value=aqi,
        unit="US AQI",
        status=FactorStatus.OK,
        detail=_category(aqi),
    )
    _cache.set(cache_key, result)
    return result
