from __future__ import annotations

from domain.models import FactorResult, FactorStatus
from infra.cache import TTLCache, geo_cache_key
from infra.geo import score_from_distance_decay
from infra.http_client import get_client
from service import osm_lookup

ADSB_URL = "https://api.adsb.lol/v2/point"

# Shorter than the 24h greenery/water/temperature caches: the live-flight component
# of this factor is transient, so a long cache would go stale quickly.
_cache = TTLCache(ttl_seconds=300)

ROAD_TAGS = [
    ("highway", "motorway"),
    ("highway", "trunk"),
    ("highway", "primary"),
]
AIRPORT_TAGS = [
    ("aeroway", "aerodrome"),
]

STRUCTURAL_RADIUS_M = 5000
ROAD_DECAY_M = 150.0
AIRPORT_DECAY_M = 3000.0

FLIGHT_RADIUS_NM = 15
FLIGHT_MAX_ALT_FT = 5000
FLIGHT_DECAY_M = 2000.0

# What to call a feature that has no name tag - "primary" or "aerodrome" is more
# useful in the detail line than "unnamed feature".
_NAME_FALLBACKS = ("highway", "aeroway")


def _is_road(el: dict) -> bool:
    return el.get("tags", {}).get("highway") in {"motorway", "trunk", "primary"}


def _is_airport(el: dict) -> bool:
    return el.get("tags", {}).get("aeroway") == "aerodrome"


def _quietness_score(distance_m: float, decay_m: float) -> float:
    """Inverse of the usual proximity-decay: close to a noise source scores LOW
    (loud/bad), far away scores HIGH (quiet/good) - the opposite relationship from
    greenery/water, where being close to the feature is what's desirable."""
    return 100.0 - score_from_distance_decay(distance_m, decay_m)


async def _nearby_low_altitude_flight(lat: float, lng: float) -> tuple[float, dict] | None:
    client = get_client()
    resp = await client.get(f"{ADSB_URL}/{lat}/{lng}/{FLIGHT_RADIUS_NM}")
    resp.raise_for_status()
    data = resp.json()
    aircraft = data.get("ac") or []

    best_dist_m: float | None = None
    best_ac: dict | None = None
    for ac in aircraft:
        alt = ac.get("alt_baro")
        dst_nm = ac.get("dst")
        if not isinstance(alt, (int, float)) or dst_nm is None or alt >= FLIGHT_MAX_ALT_FT:
            continue
        dist_m = dst_nm * 1852.0
        if best_dist_m is None or dist_m < best_dist_m:
            best_dist_m = dist_m
            best_ac = ac
    if best_ac is None or best_dist_m is None:
        return None
    return best_dist_m, best_ac


async def compute(lat: float, lng: float) -> FactorResult:
    cache_key = geo_cache_key(lat, lng)
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    # Structural signal (roads + airports): static infrastructure, so its failure
    # means we genuinely can't assess this factor.
    try:
        elements = await osm_lookup.nearby(lat, lng, ROAD_TAGS + AIRPORT_TAGS, STRUCTURAL_RADIUS_M)
    except Exception as e:
        return FactorResult(
            key="noise_sources",
            label="Noise sources",
            score=None,
            raw_value=None,
            unit=None,
            status=FactorStatus.ERROR,
            detail=f"Noise-source lookup failed: {e}",
        )

    candidates: list[tuple[float, str, float]] = []

    nearest_road = osm_lookup.nearest(lat, lng, [el for el in elements if _is_road(el)])
    if nearest_road is not None:
        dist, el = nearest_road
        name = osm_lookup.name(el, _NAME_FALLBACKS)
        candidates.append((_quietness_score(dist, ROAD_DECAY_M), f"{name} (road), {round(dist)}m", dist))

    nearest_airport = osm_lookup.nearest(lat, lng, [el for el in elements if _is_airport(el)])
    if nearest_airport is not None:
        dist, el = nearest_airport
        name = osm_lookup.name(el, _NAME_FALLBACKS)
        candidates.append((_quietness_score(dist, AIRPORT_DECAY_M), f"{name} (airport), {round(dist)}m", dist))

    # Live flight snapshot is a best-effort refinement on top of the structural read
    # above. Its failure must not invalidate an otherwise-valid structural answer, and
    # an empty result here only means "no low-altitude aircraft caught at this instant" -
    # it can sharpen the score toward louder, never toward quieter.
    try:
        flight = await _nearby_low_altitude_flight(lat, lng)
        if flight is not None:
            dist, ac = flight
            flight_label = (ac.get("flight") or "").strip() or "unidentified aircraft"
            candidates.append(
                (
                    _quietness_score(dist, FLIGHT_DECAY_M),
                    f"low-altitude aircraft {flight_label}, {round(dist)}m",
                    dist,
                )
            )
    except Exception:
        pass

    if not candidates:
        # Unlike greenery/water, absence here is the GOOD outcome: the structural
        # Overpass search above succeeded (we would have returned ERROR otherwise) and
        # confirmed nothing nearby, so this is a verified "quiet" reading, not an
        # unverified one - it must not fall through to the aggregator's pessimistic
        # floor the way a genuine not_found/error would.
        result = FactorResult(
            key="noise_sources",
            label="Noise sources",
            score=100.0,
            raw_value=None,
            unit=None,
            status=FactorStatus.OK,
            detail=f"No major road, airport, or low-altitude aircraft found within {STRUCTURAL_RADIUS_M}m",
        )
        _cache.set(cache_key, result)
        return result

    # Noise is driven by whichever source is worst - combine via the minimum score,
    # not an average, so one loud nearby source can't be diluted by quiet ones.
    worst_score, worst_detail, worst_dist = min(candidates, key=lambda c: c[0])
    result = FactorResult(
        key="noise_sources",
        label="Noise sources",
        score=round(worst_score, 1),
        raw_value=round(worst_dist, 1),
        unit="meters",
        status=FactorStatus.OK,
        detail=worst_detail,
    )
    _cache.set(cache_key, result)
    return result
