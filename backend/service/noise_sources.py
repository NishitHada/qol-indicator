from __future__ import annotations

from domain.models import FactorResult, FactorStatus
from infra.cache import TTLCache, geo_cache_key
from infra.geo import haversine_m, score_from_distance_decay
from infra.http_client import get_client
from service.overpass_batch import _post as _overpass_post

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


def _build_query(lat: float, lng: float, radius: int, tags: list[tuple[str, str]]) -> str:
    clauses = []
    for k, v in tags:
        clauses.append(f'node["{k}"="{v}"](around:{radius},{lat},{lng});')
        clauses.append(f'way["{k}"="{v}"](around:{radius},{lat},{lng});')
        clauses.append(f'relation["{k}"="{v}"](around:{radius},{lat},{lng});')
    body = "\n  ".join(clauses)
    return f"[out:json][timeout:15];\n(\n  {body}\n);\nout center 20;"


async def _query_overpass(lat: float, lng: float, radius: int, tags: list[tuple[str, str]]) -> list[dict]:
    # Shares the mirror-failover/timeout handling in overpass_batch rather than
    # hitting one hardcoded (and measurably slower) endpoint directly.
    return await _overpass_post(_build_query(lat, lng, radius, tags))


def _element_coords(el: dict) -> tuple[float, float] | None:
    if "lat" in el and "lon" in el:
        return el["lat"], el["lon"]
    center = el.get("center")
    if center:
        return center["lat"], center["lon"]
    return None


def _is_road(el: dict) -> bool:
    return el.get("tags", {}).get("highway") in {"motorway", "trunk", "primary"}


def _is_airport(el: dict) -> bool:
    return el.get("tags", {}).get("aeroway") == "aerodrome"


def _nearest_distance(lat: float, lng: float, elements: list[dict]) -> tuple[float, dict] | None:
    best_dist: float | None = None
    best_el: dict | None = None
    for el in elements:
        coords = _element_coords(el)
        if coords is None:
            continue
        d = haversine_m(lat, lng, coords[0], coords[1])
        if best_dist is None or d < best_dist:
            best_dist = d
            best_el = el
    if best_el is None or best_dist is None:
        return None
    return best_dist, best_el


def _feature_name(el: dict) -> str:
    tags = el.get("tags", {})
    return tags.get("name") or tags.get("highway") or tags.get("aeroway") or "unnamed feature"


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
        elements = await _query_overpass(lat, lng, STRUCTURAL_RADIUS_M, ROAD_TAGS + AIRPORT_TAGS)
    except Exception as e:
        return FactorResult(
            key="noise_sources",
            label="Noise sources",
            score=None,
            raw_value=None,
            unit=None,
            status=FactorStatus.ERROR,
            detail=f"Overpass request failed: {e}",
        )

    candidates: list[tuple[float, str, float]] = []

    nearest_road = _nearest_distance(lat, lng, [el for el in elements if _is_road(el)])
    if nearest_road is not None:
        dist, el = nearest_road
        candidates.append(
            (_quietness_score(dist, ROAD_DECAY_M), f"{_feature_name(el)} (road), {round(dist)}m", dist)
        )

    nearest_airport = _nearest_distance(lat, lng, [el for el in elements if _is_airport(el)])
    if nearest_airport is not None:
        dist, el = nearest_airport
        candidates.append(
            (_quietness_score(dist, AIRPORT_DECAY_M), f"{_feature_name(el)} (airport), {round(dist)}m", dist)
        )

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
