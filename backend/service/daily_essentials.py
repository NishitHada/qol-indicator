from __future__ import annotations

from dataclasses import dataclass

from domain.models import FactorResult, FactorStatus
from infra.cache import STREET_PRECISION, TTLCache, geo_cache_key
from infra.geo import score_within_walk
from service import osm_lookup

_cache = TTLCache(ttl_seconds=86400)

SEARCH_RADIUS_M = 3000

KEY = "daily_essentials"
LABEL = "Daily essentials nearby"


@dataclass(frozen=True)
class EssentialGroup:
    label: str
    tags: list[tuple[str, str]]
    full_credit_m: float
    decay_m: float


# One entry per errand a household actually runs, not per OSM tag - a location with
# four supermarkets and no pharmacy is not well served, and scoring the nearest single
# amenity would call it excellent. Distances are what people will genuinely walk for
# that specific errand: groceries daily, a bank rarely.
GROUPS = [
    EssentialGroup(
        label="groceries",
        tags=[
            ("shop", "supermarket"),
            ("shop", "convenience"),
            ("shop", "greengrocer"),
            ("amenity", "marketplace"),
        ],
        full_credit_m=500.0,
        decay_m=700.0,
    ),
    EssentialGroup(
        label="pharmacy",
        tags=[("amenity", "pharmacy")],
        full_credit_m=700.0,
        decay_m=900.0,
    ),
    EssentialGroup(
        label="school",
        tags=[("amenity", "school")],
        full_credit_m=1000.0,
        decay_m=1500.0,
    ),
    EssentialGroup(
        label="banking",
        tags=[("amenity", "bank"), ("amenity", "atm")],
        full_credit_m=800.0,
        decay_m=1200.0,
    ),
]

ALL_TAGS = sorted({tag for group in GROUPS for tag in group.tags})


async def compute(lat: float, lng: float) -> FactorResult:
    cache_key = geo_cache_key(lat, lng, precision=STREET_PRECISION)
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        elements = await osm_lookup.nearby(lat, lng, ALL_TAGS, SEARCH_RADIUS_M)
    except Exception as e:
        return FactorResult(
            key=KEY,
            label=LABEL,
            score=None,
            raw_value=None,
            unit=None,
            status=FactorStatus.ERROR,
            detail=f"Amenity lookup failed: {e}",
        )

    scores: list[float] = []
    covered: list[str] = []
    missing: list[str] = []
    for group in GROUPS:
        found = osm_lookup.nearest(lat, lng, [el for el in elements if osm_lookup.matches(el, group.tags)])
        if found is None:
            # A missing errand scores zero rather than dropping out of the average.
            # Averaging only over what we found would let a location with nothing but
            # a school score 100 for "daily essentials", which is exactly the false
            # positive this app is built to avoid.
            scores.append(0.0)
            missing.append(group.label)
            continue
        distance, _ = found
        scores.append(score_within_walk(distance, group.full_credit_m, group.decay_m))
        covered.append(f"{group.label} {round(distance)}m")

    # The mean across errands, so no single well-served category can carry the score.
    score = sum(scores) / len(scores)
    detail = ", ".join(covered) if covered else "none found"
    if missing:
        detail = f"{detail}; no {'/'.join(missing)} within {SEARCH_RADIUS_M}m"

    result = FactorResult(
        key=KEY,
        label=LABEL,
        score=round(score, 1),
        raw_value=len(covered),
        unit=f"of {len(GROUPS)} essentials nearby",
        status=FactorStatus.OK,
        source="osm",
        detail=detail,
    )
    _cache.set(cache_key, result)
    return result
