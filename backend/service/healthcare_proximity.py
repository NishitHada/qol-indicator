from __future__ import annotations

from domain.models import FactorResult, FactorStatus
from infra.cache import TTLCache, geo_cache_key
from service.overpass_proximity import nearest_proximity_result

_cache = TTLCache(ttl_seconds=86400)

KEY = "healthcare_proximity"
LABEL = "Healthcare proximity"
TAGS = [
    ("amenity", "hospital"),
    ("amenity", "clinic"),
]
DECAY_M = 1500.0
# Hospitals/clinics are sparser than parks or cafes, so search wider before giving up.
PRIMARY_RADIUS_M = 5000
FALLBACK_RADIUS_M = 15000


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
        primary_radius_m=PRIMARY_RADIUS_M,
        fallback_radius_m=FALLBACK_RADIUS_M,
        name_tag_keys=("name", "amenity"),
    )
    if result.status != FactorStatus.ERROR:
        _cache.set(cache_key, result)
    return result
