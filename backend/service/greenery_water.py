from __future__ import annotations

from domain.models import FactorResult
from service.overpass_batch import compute_categories
from service.overpass_categories import GREENERY, WATER


async def compute_greenery(lat: float, lng: float) -> FactorResult:
    results = await compute_categories(lat, lng, [GREENERY])
    return results[GREENERY.key]


async def compute_water(lat: float, lng: float) -> FactorResult:
    results = await compute_categories(lat, lng, [WATER])
    return results[WATER.key]
