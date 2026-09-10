from __future__ import annotations

from dataclasses import dataclass

from domain.models import FactorResult, FactorStatus, TransportPreference, UserProfile
from infra.cache import STREET_PRECISION, TTLCache, geo_cache_key
from infra.geo import score_within_walk
from service import osm_lookup

_cache = TTLCache(ttl_seconds=86400)

SEARCH_RADIUS_M = 3000

KEY = "connectivity"
LABEL = "Public transport connectivity"


@dataclass(frozen=True)
class TransitMode:
    label: str
    # Which stated transport preference this mode satisfies. A user who says "metro"
    # is not served by the bus stop outside their door, so preference filtering is on
    # this rather than on the label.
    group: str
    tags: list[tuple[str, str]]
    full_credit_m: float
    decay_m: float
    ceiling: float
    # Applied after the tag match, for modes that share a tag with another mode.
    require: tuple[str, str] | None = None
    exclude: tuple[str, str] | None = None


# Ceilings are the important part of this table, not the distances. They encode how
# much each mode is allowed to certify on its own, which is the "no false positives"
# rule applied to transit: a single mapped bus stop is real evidence of *some* transit
# access, but it is not evidence of a well-connected address - BMTC frequencies vary
# enormously by route and OSM records the stop, not the service. A metro station is,
# so only metro can carry a location to 100.
MODES = [
    TransitMode(
        label="metro station",
        group="metro",
        tags=[("railway", "station"), ("public_transport", "station")],
        require=("station", "subway"),
        full_credit_m=600.0,
        decay_m=900.0,
        ceiling=100.0,
    ),
    TransitMode(
        label="metro entrance",
        group="metro",
        tags=[("railway", "subway_entrance")],
        full_credit_m=500.0,
        decay_m=800.0,
        ceiling=100.0,
    ),
    TransitMode(
        label="railway station",
        group="rail",
        tags=[("railway", "station"), ("railway", "halt")],
        exclude=("station", "subway"),
        full_credit_m=800.0,
        decay_m=1200.0,
        ceiling=85.0,
    ),
    TransitMode(
        label="bus interchange",
        group="bus",
        tags=[("public_transport", "station")],
        exclude=("station", "subway"),
        full_credit_m=500.0,
        decay_m=800.0,
        ceiling=80.0,
    ),
    TransitMode(
        label="bus stop",
        group="bus",
        tags=[("highway", "bus_stop")],
        full_credit_m=400.0,
        decay_m=600.0,
        ceiling=65.0,
    ),
]

ALL_TAGS = sorted({tag for mode in MODES for tag in mode.tags})

# Which mode groups count for each stated preference. CAB is absent on purpose: it
# does not narrow this factor, it removes it (see service/personalization.py), because
# someone who always takes a cab is neither served nor underserved by a nearby stop.
PREFERRED_GROUPS = {
    TransportPreference.METRO: {"metro"},
    TransportPreference.BUS: {"bus"},
}


def modes_for(profile: UserProfile | None) -> list[TransitMode]:
    if profile is None or profile.transport_preference is None:
        return MODES
    groups = PREFERRED_GROUPS.get(profile.transport_preference)
    if groups is None:
        return MODES
    return [mode for mode in MODES if mode.group in groups]


def _described(modes: list[TransitMode]) -> str:
    """What we actually looked for, so a metro user is not told there is 'no transit'
    when the street is lined with bus stops."""
    if modes is MODES:
        return "bus, metro or rail stop"
    return " or ".join(sorted({mode.group for mode in modes})) + " stop"


def _mode_elements(mode: TransitMode, elements: list[dict]) -> list[dict]:
    out = []
    for el in elements:
        tags = el.get("tags", {})
        if not any(tags.get(k) == v for k, v in mode.tags):
            continue
        if mode.require and tags.get(mode.require[0]) != mode.require[1]:
            continue
        if mode.exclude and tags.get(mode.exclude[0]) == mode.exclude[1]:
            continue
        out.append(el)
    return out


async def compute(lat: float, lng: float, profile: UserProfile | None = None) -> FactorResult:
    modes = modes_for(profile)
    preference = profile.transport_preference.value if profile and profile.transport_preference else "any"
    # The preference is part of the key: the same point scores differently for a metro
    # user than for a bus user, and serving one the other's cached answer is exactly
    # the class of bug the cache-precision work already had to fix once.
    cache_key = f"{preference}:{geo_cache_key(lat, lng, precision=STREET_PRECISION)}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        wanted_tags = sorted({tag for mode in modes for tag in mode.tags})
        elements = await osm_lookup.nearby(lat, lng, wanted_tags, SEARCH_RADIUS_M)
    except Exception as e:
        return FactorResult(
            key=KEY,
            label=LABEL,
            score=None,
            raw_value=None,
            unit=None,
            status=FactorStatus.ERROR,
            detail=f"Transit lookup failed: {e}",
        )

    best: tuple[float, float, str] | None = None  # (score, distance, detail)
    for mode in modes:
        found = osm_lookup.nearest(lat, lng, _mode_elements(mode, elements))
        if found is None:
            continue
        distance, el = found
        score = score_within_walk(distance, mode.full_credit_m, mode.decay_m, ceiling=mode.ceiling)
        detail = f"{osm_lookup.name(el)} ({mode.label}), {round(distance)}m"
        if best is None or score > best[0]:
            best = (score, distance, detail)

    if best is None:
        # Unlike noise, absence here is genuinely bad news rather than good news, but
        # it is also a real finding inside the bundled extract, not a failed lookup -
        # so it is a verified 0, not an unverified floor.
        result = FactorResult(
            key=KEY,
            label=LABEL,
            score=0.0,
            raw_value=None,
            unit=None,
            status=FactorStatus.OK,
            source="osm",
            detail=(
                f"No {_described(modes)} mapped within {SEARCH_RADIUS_M}m"
            ),
        )
        _cache.set(cache_key, result)
        return result

    # Best mode wins rather than an average across modes: a metro station 400m away
    # makes a location well-connected regardless of how far the nearest bus stop is,
    # and averaging would let a missing mode drag down a genuinely good answer.
    score, distance, detail = best
    result = FactorResult(
        key=KEY,
        label=LABEL,
        score=round(score, 1),
        raw_value=round(distance, 1),
        unit="meters",
        status=FactorStatus.OK,
        source="osm",
        detail=detail,
    )
    _cache.set(cache_key, result)
    return result
