from __future__ import annotations

import asyncio

from domain.models import UNVERIFIED_FLOOR_SCORE, FactorResult, FactorStatus
from service import vendor_fallback
from service.registry import FACTOR_REGISTRY


async def compute_all(lat: float, lng: float) -> dict[str, FactorResult]:
    enabled_defs = [d for d in FACTOR_REGISTRY if d.enabled]
    disabled_defs = [d for d in FACTOR_REGISTRY if not d.enabled]

    enabled_results = await asyncio.gather(*(vendor_fallback.resolve(d, lat, lng) for d in enabled_defs))
    by_key: dict[str, FactorResult] = {r.key: r for r in enabled_results}

    for d in disabled_defs:
        by_key[d.key] = await d.vendors[0].compute(lat, lng)

    return by_key


def compute_overall(factor_results: dict[str, FactorResult]) -> tuple[float, dict[str, float], list[str]]:
    """Weighted composite over the enabled (v1) factors.

    Weights are fixed and never renormalized: a factor we couldn't verify
    (not_found/error) contributes UNVERIFIED_FLOOR_SCORE rather than being
    excluded, so uncertainty can only pull the score down, never up.
    """
    enabled_defs = [d for d in FACTOR_REGISTRY if d.enabled]
    weights_used: dict[str, float] = {}
    unverified: list[str] = []
    total = 0.0

    for definition in enabled_defs:
        weights_used[definition.key] = definition.weight
        result = factor_results.get(definition.key)
        if result is not None and result.status == FactorStatus.OK and result.score is not None:
            total += definition.weight * result.score
        else:
            total += definition.weight * UNVERIFIED_FLOOR_SCORE
            unverified.append(definition.key)

    overall = round(total, 1) if enabled_defs else 0.0
    return overall, weights_used, unverified
