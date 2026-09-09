from __future__ import annotations

from domain.models import FactorResult, FactorStatus
from infra.cache import TTLCache, geo_cache_key
from service.overpass_proximity import nearest_proximity_result

_cache = TTLCache(ttl_seconds=86400)

KEY = "religious_site_proximity"
LABEL = "Religious site proximity"
TAGS = [
    ("amenity", "place_of_worship"),
]
DECAY_M = 800.0


async def compute(lat: float, lng: float) -> FactorResult:
    cache_key = geo_cache_key(lat, lng)
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    result = await nearest_proximity_result(
        lat,
        lng,
        key=KEY,
        label=LABEL,
        tags=TAGS,
        decay_m=DECAY_M,
        name_tag_keys=("name", "religion", "denomination"),
    )
    if result.status != FactorStatus.ERROR:
        _cache.set(cache_key, result)
    return result
