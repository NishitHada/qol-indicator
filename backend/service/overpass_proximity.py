from __future__ import annotations

from domain.models import FactorResult, FactorStatus
from infra.geo import haversine_m, score_from_distance_decay
from infra.http_client import get_client

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def build_query(lat: float, lng: float, radius: int, tags: list[tuple[str, str]]) -> str:
    clauses = []
    for k, v in tags:
        clauses.append(f'node["{k}"="{v}"](around:{radius},{lat},{lng});')
        clauses.append(f'way["{k}"="{v}"](around:{radius},{lat},{lng});')
        clauses.append(f'relation["{k}"="{v}"](around:{radius},{lat},{lng});')
    body = "\n  ".join(clauses)
    return f"[out:json][timeout:15];\n(\n  {body}\n);\nout center 20;"


async def query_overpass(lat: float, lng: float, radius: int, tags: list[tuple[str, str]]) -> list[dict]:
    client = get_client()
    query = build_query(lat, lng, radius, tags)
    resp = await client.post(OVERPASS_URL, data={"data": query})
    resp.raise_for_status()
    data = resp.json()
    return data.get("elements", [])


def element_coords(el: dict) -> tuple[float, float] | None:
    if "lat" in el and "lon" in el:
        return el["lat"], el["lon"]
    center = el.get("center")
    if center:
        return center["lat"], center["lon"]
    return None


def nearest(lat: float, lng: float, elements: list[dict]) -> tuple[float, dict] | None:
    best_dist: float | None = None
    best_el: dict | None = None
    for el in elements:
        coords = element_coords(el)
        if coords is None:
            continue
        d = haversine_m(lat, lng, coords[0], coords[1])
        if best_dist is None or d < best_dist:
            best_dist = d
            best_el = el
    if best_el is None or best_dist is None:
        return None
    return best_dist, best_el


def feature_name(el: dict, name_tag_keys: tuple[str, ...] = ("name",)) -> str:
    tags = el.get("tags", {})
    for k in name_tag_keys:
        v = tags.get(k)
        if v:
            return v
    return "unnamed feature"


async def nearest_proximity_result(
    lat: float,
    lng: float,
    *,
    key: str,
    label: str,
    tags: list[tuple[str, str]],
    decay_m: float,
    primary_radius_m: int = 3000,
    fallback_radius_m: int = 8000,
    name_tag_keys: tuple[str, ...] = ("name",),
) -> FactorResult:
    """Shared 'closer is better' Overpass proximity computation. Caching is the
    caller's responsibility - this function is stateless."""
    try:
        elements = await query_overpass(lat, lng, primary_radius_m, tags)
        radius_used = primary_radius_m
        if not elements:
            elements = await query_overpass(lat, lng, fallback_radius_m, tags)
            radius_used = fallback_radius_m
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

    found = nearest(lat, lng, elements)
    if found is None:
        return FactorResult(
            key=key,
            label=label,
            score=None,
            raw_value=None,
            unit=None,
            status=FactorStatus.NOT_FOUND,
            detail=f"No {label.lower()} found within {radius_used}m",
        )

    distance_m, el = found
    score = score_from_distance_decay(distance_m, decay_m)
    return FactorResult(
        key=key,
        label=label,
        score=round(score, 1),
        raw_value=round(distance_m, 1),
        unit="meters",
        status=FactorStatus.OK,
        detail=f"{feature_name(el, name_tag_keys)}, {round(distance_m)}m",
    )
