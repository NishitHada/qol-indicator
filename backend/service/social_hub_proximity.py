from __future__ import annotations

from domain.models import FactorResult
from service.overpass_batch import compute_categories
from service.overpass_categories import SOCIAL_HUB


async def compute(lat: float, lng: float) -> FactorResult:
    results = await compute_categories(lat, lng, [SOCIAL_HUB])
    return results[SOCIAL_HUB.key]
