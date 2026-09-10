from __future__ import annotations

import math
from dataclasses import dataclass

from domain.models import FactorResult, FactorStatus
from infra.cache import STREET_PRECISION, TTLCache, geo_cache_key
from infra.geo import haversine_m, score_from_distance_decay
from service import osm_lookup

_cache = TTLCache(ttl_seconds=86400)

SEARCH_RADIUS_M = 4000


@dataclass(frozen=True)
class Nuisance:
    label: str
    tags: list[tuple[str, str]]
    # Distance at which this source's effect has decayed to ~37% of maximum. Set from
    # how far the nuisance actually travels, which is why a landfill's is several
    # times an industrial estate's - smell carries much further than a factory's
    # particulate footprint.
    decay_m: float
    # How bad this source is when you are right on top of it, 0-100. Nothing reaches
    # 100: even a landfill next door does not make a location score zero on its own.
    severity: float
    # Footprint of a full-scale example of this source, in square metres. Both numbers
    # above describe a source of roughly this size; a *smaller* mapped footprint
    # scales them down (see _size_scale). Set from the measured p75 footprint of each
    # type in the bundled extract, so "typical" means typical for Bangalore.
    full_scale_area_m2: float


# Below this fraction, shrinking the footprint stops mattering - a nuisance is still a
# nuisance at the boundary fence however small it is.
MIN_SEVERITY_SCALE = 0.25
MIN_DECAY_SCALE = 0.4


def _size_scale(area_m2: float | None, full_scale_area_m2: float) -> float:
    """How much of a full-scale source's impact a mapped feature gets, from its area.

    Unmapped area returns 1.0 - full impact. That asymmetry is deliberate and is the
    "no false positives" rule applied here: this only ever *reduces* a penalty, and
    only when the map positively proves the source is small. An unmapped footprint is
    treated as a full-scale source, so missing data can never talk us into approving a
    location we should have flagged.

    Square-root because impact scales with a plume's linear extent rather than the
    plant's floor area. Bangalore mandates a sewage treatment plant in every apartment
    complex over a certain size; without this, hundreds of shed-sized units score the
    same as the municipal plants at Bellandur, and almost every address in the city
    ends up wrongly penalised. Cubbon Park's 6,243 m2 plant was scoring the park at 53.
    """
    if not area_m2:
        return 1.0
    return min(1.0, math.sqrt(area_m2 / full_scale_area_m2))


AIRBORNE = [
    Nuisance("landfill", [("landuse", "landfill")], 1500.0, 95.0, full_scale_area_m2=100_000),
    Nuisance("sewage treatment plant", [("man_made", "wastewater_plant")], 1000.0, 90.0, full_scale_area_m2=50_000),
    Nuisance("quarry", [("landuse", "quarry")], 1200.0, 85.0, full_scale_area_m2=175_000),
    Nuisance("industrial works", [("man_made", "works")], 700.0, 80.0, full_scale_area_m2=25_000),
    Nuisance(
        "waste depot",
        [("amenity", "waste_disposal"), ("amenity", "waste_transfer_station")],
        500.0,
        75.0,
        full_scale_area_m2=5_000,
    ),
    Nuisance("industrial area", [("landuse", "industrial")], 600.0, 60.0, full_scale_area_m2=40_000),
]

# Odour is a strict subset: an industrial estate degrades air quality without
# necessarily smelling, whereas a landfill or a sewage plant is smelled kilometres
# away. The decay distances are correspondingly longer here than above, because what
# reaches you as a smell travels further than what reaches you as measurable pollution.
ODOUR = [
    Nuisance("landfill", [("landuse", "landfill")], 2000.0, 95.0, full_scale_area_m2=100_000),
    Nuisance("sewage treatment plant", [("man_made", "wastewater_plant")], 1500.0, 95.0, full_scale_area_m2=50_000),
    Nuisance(
        "waste depot",
        [("amenity", "waste_disposal"), ("amenity", "waste_transfer_station")],
        700.0,
        80.0,
        full_scale_area_m2=5_000,
    ),
]

_ALL_TAGS = sorted({tag for n in AIRBORNE + ODOUR for tag in n.tags})


async def _compute(lat: float, lng: float, key: str, label: str, nuisances: list[Nuisance]) -> FactorResult:
    cache_key = f"{key}:{geo_cache_key(lat, lng, precision=STREET_PRECISION)}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        elements = await osm_lookup.nearby(lat, lng, _ALL_TAGS, SEARCH_RADIUS_M)
    except Exception as e:
        return FactorResult(
            key=key,
            label=label,
            score=None,
            raw_value=None,
            unit=None,
            status=FactorStatus.ERROR,
            detail=f"Pollution-source lookup failed: {e}",
        )

    worst: tuple[float, float, str] | None = None  # (score, distance, detail)
    for nuisance in nuisances:
        # Every matching source is scored, not just the nearest one: a small plant next
        # door can be less of a problem than the landfill a kilometre away, so picking
        # by distance first would decide the answer before scoring it.
        for el in elements:
            if not osm_lookup.matches(el, nuisance.tags):
                continue
            point = osm_lookup.coords(el)
            if point is None:
                continue
            distance = haversine_m(lat, lng, point[0], point[1])
            scale = _size_scale(el.get("area_m2"), nuisance.full_scale_area_m2)
            severity = nuisance.severity * max(scale, MIN_SEVERITY_SCALE)
            decay = nuisance.decay_m * max(scale, MIN_DECAY_SCALE)
            # Inverted decay, as in noise_sources: close to a nuisance is bad, far is
            # good. Scaled by severity so the ceiling of the penalty differs per source
            # type rather than every source being equally ruinous at zero metres.
            score = 100.0 - severity / 100.0 * score_from_distance_decay(distance, decay)
            if worst is None or score < worst[0]:
                # No fallback tag keys: a feature carrying both landuse=industrial and
                # man_made=wastewater_plant would otherwise be reported as "industrial
                # (sewage treatment plant)". The nuisance's own label already says what
                # it is, so an unnamed feature needs nothing more.
                named = el.get("tags", {}).get("name")
                label_text = f"{named} ({nuisance.label})" if named else nuisance.label
                worst = (score, distance, f"{label_text}, {round(distance)}m")

    if worst is None:
        # The lookup succeeded and found nothing, which for a nuisance factor is the
        # good outcome - a verified clean reading, not an unverified one. Returning
        # NOT_FOUND here would push it to the aggregator's pessimistic floor and
        # penalise exactly the locations that deserve the opposite.
        result = FactorResult(
            key=key,
            label=label,
            score=100.0,
            raw_value=None,
            unit=None,
            status=FactorStatus.OK,
            source="osm",
            detail=f"No {label.lower()} mapped within {SEARCH_RADIUS_M}m",
        )
        _cache.set(cache_key, result)
        return result

    # Worst source wins, not an average: living beside a sewage plant is not made
    # better by the absence of a quarry.
    score, distance, detail = worst
    result = FactorResult(
        key=key,
        label=label,
        score=round(score, 1),
        raw_value=round(distance, 1),
        unit="meters",
        status=FactorStatus.OK,
        source="osm",
        detail=detail,
    )
    _cache.set(cache_key, result)
    return result


async def compute_pollution(lat: float, lng: float) -> FactorResult:
    return await _compute(lat, lng, "pollution_sources", "Pollution sources", AIRBORNE)


async def compute_odour(lat: float, lng: float) -> FactorResult:
    return await _compute(lat, lng, "bad_odour", "Bad odour", ODOUR)
