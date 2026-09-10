from __future__ import annotations

from domain.models import FactorResult, FactorStatus
from infra.cache import STREET_PRECISION, TTLCache, geo_cache_key
from service import local_buildings

_cache = TTLCache(ttl_seconds=86400)

KEY = "crowding"
LABEL = "Crowding & open space"

# Cells are ~220m, so radius 1 samples a ~660m square around the point - a few blocks,
# which is the scale at which crowding is actually experienced.
SAMPLE_RADIUS_CELLS = 1

# Share of the ground covered by building footprints. Both ends are taken from the
# measured distribution over Bangalore rather than picked: 15% sits near the quartile
# of built-up cells, and above 45% a neighbourhood has essentially no setbacks left.
GOOD_COVERAGE_PCT = 15.0
BAD_COVERAGE_PCT = 45.0


def _score_from_coverage(coverage_pct: float) -> float:
    if coverage_pct <= GOOD_COVERAGE_PCT:
        return 100.0
    if coverage_pct >= BAD_COVERAGE_PCT:
        return 0.0
    span = BAD_COVERAGE_PCT - GOOD_COVERAGE_PCT
    return 100.0 * (BAD_COVERAGE_PCT - coverage_pct) / span


async def compute(lat: float, lng: float) -> FactorResult:
    cache_key = geo_cache_key(lat, lng, precision=STREET_PRECISION)
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    sample = local_buildings.sample(lat, lng, SAMPLE_RADIUS_CELLS)
    if sample is None:
        # Outside the bundled area. There is no live vendor for this dataset, so this
        # is a genuine "cannot verify" and gets the aggregator's conservative floor
        # rather than a guess.
        return FactorResult(
            key=KEY,
            label=LABEL,
            score=None,
            raw_value=None,
            unit=None,
            status=FactorStatus.NOT_FOUND,
            detail="Outside the bundled building-footprint area",
        )

    coverage = sample.coverage_pct
    if sample.building_count == 0:
        # Genuinely nothing built nearby. Unlike OpenStreetMap, this dataset is
        # machine-extracted uniformly across the whole area, so an empty cell is
        # evidence of open land rather than of nobody having mapped it - which is why
        # this is a verified 100 and not a "cannot verify". Whether open land is a
        # *good* place to live is what connectivity and daily essentials decide.
        detail = "No buildings within ~660m: open land"
    else:
        detail = (
            f"{coverage:.0f}% built coverage, {sample.buildings_per_hectare:.0f} buildings/ha, "
            f"typical footprint {sample.typical_footprint_m2:.0f} m²"
        )

    result = FactorResult(
        key=KEY,
        label=LABEL,
        score=round(_score_from_coverage(coverage), 1),
        raw_value=round(coverage, 1),
        unit="% ground covered by buildings",
        status=FactorStatus.OK,
        source="ms-global-ml-building-footprints",
        detail=detail,
    )
    _cache.set(cache_key, result)
    return result
