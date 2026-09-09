from __future__ import annotations

from domain.models import FactorResult
from service.overpass_batch import compute_categories
from service.overpass_categories import HEALTHCARE


async def compute(lat: float, lng: float) -> FactorResult:
    results = await compute_categories(lat, lng, [HEALTHCARE])
    return results[HEALTHCARE.key]
