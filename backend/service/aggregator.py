from __future__ import annotations

import asyncio

from domain.models import UNVERIFIED_FLOOR_SCORE, FactorResult, FactorStatus, UserProfile
from service import overpass_batch, personalization, vendor_fallback
from service.overpass_categories import ALL_CATEGORIES
from service.registry import FACTOR_REGISTRY

# Keys resolved via one batched Overpass call (service/overpass_batch.py) instead of
# each firing its own independent request through vendor_fallback. Five factors each
# hitting the same free public Overpass instance separately was the biggest source of
# the "N factors couldn't be verified" rate-limiting seen in practice - this collapses
# it to one call (two if some categories need a fallback-radius retry).
_BATCHED_OVERPASS_KEYS = frozenset(c.key for c in ALL_CATEGORIES)


async def compute_all(lat: float, lng: float) -> dict[str, FactorResult]:
    enabled_defs = [d for d in FACTOR_REGISTRY if d.enabled]
    disabled_defs = [d for d in FACTOR_REGISTRY if not d.enabled]

    batchable_defs = [d for d in enabled_defs if d.key in _BATCHED_OVERPASS_KEYS]
    individual_defs = [d for d in enabled_defs if d.key not in _BATCHED_OVERPASS_KEYS]
    batch_categories = [c for c in ALL_CATEGORIES if c.key in {d.key for d in batchable_defs}]

    batch_results, individual_results = await asyncio.gather(
        overpass_batch.compute_categories(lat, lng, batch_categories) if batch_categories else _empty(),
        asyncio.gather(*(vendor_fallback.resolve(d, lat, lng) for d in individual_defs)),
    )

    by_key: dict[str, FactorResult] = dict(batch_results)
    by_key.update({r.key: r for r in individual_results})

    for d in disabled_defs:
        by_key[d.key] = await d.vendors[0].compute(lat, lng)

    return by_key


async def _empty() -> dict[str, FactorResult]:
    return {}


def compute_overall(
    factor_results: dict[str, FactorResult], profile: UserProfile | None = None
) -> tuple[float, dict[str, float], list[str], list[str]]:
    """Weighted composite over the enabled (v1) factors.

    With no profile (the default), weights are exactly each factor's registry weight -
    fixed, never renormalized away from a factor that couldn't be verified: a factor
    with not_found/error contributes UNVERIFIED_FLOOR_SCORE rather than being
    excluded, so uncertainty can only pull the score down, never up.

    With a profile, weights are first adjusted by any matching personalization rules
    (see service/personalization.py) and renormalized to sum to 1.0 - this only
    shifts relative emphasis between factors, it never changes the floor-on-failure
    behavior above or the 0-100 range of the result.
    """
    enabled_defs = [d for d in FACTOR_REGISTRY if d.enabled]
    base_weights = {d.key: d.weight for d in enabled_defs}
    weights_used, personalization_applied = personalization.adjusted_weights(base_weights, profile)

    unverified: list[str] = []
    total = 0.0

    for definition in enabled_defs:
        weight = weights_used[definition.key]
        result = factor_results.get(definition.key)
        if result is not None and result.status == FactorStatus.OK and result.score is not None:
            total += weight * result.score
        else:
            total += weight * UNVERIFIED_FLOOR_SCORE
            unverified.append(definition.key)

    overall = round(total, 1) if enabled_defs else 0.0
    return overall, weights_used, unverified, personalization_applied
