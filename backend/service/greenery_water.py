from __future__ import annotations

import math

from domain.models import FactorResult, FactorStatus
from infra.cache import TTLCache, geo_cache_key
from infra.http_client import get_client

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

_greenery_cache = TTLCache(ttl_seconds=86400)
_water_cache = TTLCache(ttl_seconds=86400)

GREENERY_TAGS = [
    ("leisure", "park"),
    ("landuse", "forest"),
    ("natural", "wood"),
]
WATER_TAGS = [
    ("natural", "water"),
    ("waterway", "river"),
    ("waterway", "stream"),
]

GREENERY_DECAY_M = 500.0
WATER_DECAY_M = 800.0

PRIMARY_RADIUS_M = 3000
FALLBACK_RADIUS_M = 8000


def _build_query(lat: float, lng: float, radius: int, tags: list[tuple[str, str]]) -> str:
    clauses = []
    for k, v in tags:
        clauses.append(f'node["{k}"="{v}"](around:{radius},{lat},{lng});')
        clauses.append(f'way["{k}"="{v}"](around:{radius},{lat},{lng});')
        clauses.append(f'relation["{k}"="{v}"](around:{radius},{lat},{lng});')
    body = "\n  ".join(clauses)
    return f"[out:json][timeout:15];\n(\n  {body}\n);\nout center 20;"


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_earth_m = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius_earth_m * math.asin(math.sqrt(a))


async def _query_overpass(lat: float, lng: float, radius: int, tags: list[tuple[str, str]]) -> list[dict]:
    client = get_client()
    query = _build_query(lat, lng, radius, tags)
    resp = await client.post(OVERPASS_URL, data={"data": query})
    resp.raise_for_status()
    data = resp.json()
    return data.get("elements", [])


def _element_coords(el: dict) -> tuple[float, float] | None:
    if "lat" in el and "lon" in el:
        return el["lat"], el["lon"]
    center = el.get("center")
    if center:
        return center["lat"], center["lon"]
    return None


def _nearest(lat: float, lng: float, elements: list[dict]) -> tuple[float, dict] | None:
    best_dist: float | None = None
    best_el: dict | None = None
    for el in elements:
        coords = _element_coords(el)
        if coords is None:
            continue
        d = _haversine_m(lat, lng, coords[0], coords[1])
        if best_dist is None or d < best_dist:
            best_dist = d
            best_el = el
    if best_el is None or best_dist is None:
        return None
    return best_dist, best_el


def _feature_name(el: dict) -> str:
    tags = el.get("tags", {})
    return (
        tags.get("name")
        or tags.get("leisure")
        or tags.get("natural")
        or tags.get("landuse")
        or tags.get("waterway")
        or "unnamed feature"
    )


def _score_from_distance(distance_m: float, decay_m: float) -> float:
    return max(0.0, min(100.0, 100.0 * math.exp(-distance_m / decay_m)))


async def _compute(
    lat: float,
    lng: float,
    tags: list[tuple[str, str]],
    decay_m: float,
    key: str,
    label: str,
    cache: TTLCache,
) -> FactorResult:
    cache_key = geo_cache_key(lat, lng)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        elements = await _query_overpass(lat, lng, PRIMARY_RADIUS_M, tags)
        radius_used = PRIMARY_RADIUS_M
        if not elements:
            elements = await _query_overpass(lat, lng, FALLBACK_RADIUS_M, tags)
            radius_used = FALLBACK_RADIUS_M
    except Exception as e:
        return FactorResult(
            key=key,
            label=label,
            score=None,
            raw_value=None,
            unit=None,
            status=FactorStatus.ERROR,
            detail=f"Overpass request failed: {e}",
        )

    nearest = _nearest(lat, lng, elements)
    if nearest is None:
        result = FactorResult(
            key=key,
            label=label,
            score=None,
            raw_value=None,
            unit=None,
            status=FactorStatus.NOT_FOUND,
            detail=f"No {label.lower()} found within {radius_used}m",
        )
        cache.set(cache_key, result)
        return result

    distance_m, el = nearest
    score = _score_from_distance(distance_m, decay_m)
    result = FactorResult(
        key=key,
        label=label,
        score=round(score, 1),
        raw_value=round(distance_m, 1),
        unit="meters",
        status=FactorStatus.OK,
        detail=f"{_feature_name(el)}, {round(distance_m)}m",
    )
    cache.set(cache_key, result)
    return result


async def compute_greenery(lat: float, lng: float) -> FactorResult:
    return await _compute(
        lat, lng, GREENERY_TAGS, GREENERY_DECAY_M, "greenery_proximity", "Greenery proximity", _greenery_cache
    )


async def compute_water(lat: float, lng: float) -> FactorResult:
    return await _compute(
        lat, lng, WATER_TAGS, WATER_DECAY_M, "water_proximity", "Water proximity", _water_cache
    )
