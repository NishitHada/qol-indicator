from __future__ import annotations

from domain.models import FactorResult
from service.overpass_batch import compute_categories
from service.overpass_categories import RELIGIOUS_SITE


async def compute(lat: float, lng: float) -> FactorResult:
    results = await compute_categories(lat, lng, [RELIGIOUS_SITE])
    return results[RELIGIOUS_SITE.key]
