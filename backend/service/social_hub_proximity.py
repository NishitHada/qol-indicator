from __future__ import annotations

from domain.models import FactorResult, FactorStatus
from infra.cache import TTLCache, geo_cache_key
from service.overpass_proximity import nearest_proximity_result

_cache = TTLCache(ttl_seconds=86400)

KEY = "social_hub_proximity"
LABEL = "Social hub proximity"
TAGS = [
    ("amenity", "bar"),
    ("amenity", "nightclub"),
    ("amenity", "cafe"),
    ("shop", "mall"),
]
DECAY_M = 400.0


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
        name_tag_keys=("name", "amenity", "shop"),
    )
    if result.status != FactorStatus.ERROR:
        _cache.set(cache_key, result)
    return result
