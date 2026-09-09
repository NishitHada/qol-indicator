from __future__ import annotations

from infra.geo import haversine_m
from service import local_osm
from service.overpass_batch import _post as _overpass_post


def _build_query(lat: float, lng: float, radius_m: int, tags: list[tuple[str, str]]) -> str:
    clauses = []
    for k, v in tags:
        clauses.append(f'node["{k}"="{v}"](around:{radius_m},{lat},{lng});')
        clauses.append(f'way["{k}"="{v}"](around:{radius_m},{lat},{lng});')
        clauses.append(f'relation["{k}"="{v}"](around:{radius_m},{lat},{lng});')
    body = "\n  ".join(clauses)
    return f"[out:json][timeout:25];\n(\n  {body}\n);\nout center 200;"


async def nearby(lat: float, lng: float, tags: list[tuple[str, str]], radius_m: int) -> list[dict]:
    """Features carrying any of `tags` within `radius_m`, in Overpass's element shape.

    Inside the bundled extract's area this needs no network at all; outside it, the
    query goes through overpass_batch's mirror failover rather than a hardcoded
    endpoint. Every factor that reads OSM features but isn't a plain single-category
    proximity lookup (connectivity, daily essentials, pollution, noise) shares this,
    so the bundled-first behaviour is defined in exactly one place.
    """
    if local_osm.covers(lat, lng):
        return local_osm.elements_near(lat, lng, tags, radius_m)
    elements = await _overpass_post(_build_query(lat, lng, radius_m, tags))
    return [el for el in elements if matches(el, tags)]


def matches(el: dict, tags: list[tuple[str, str]]) -> bool:
    el_tags = el.get("tags", {})
    return any(el_tags.get(k) == v for k, v in tags)


def coords(el: dict) -> tuple[float, float] | None:
    if "lat" in el and "lon" in el:
        return el["lat"], el["lon"]
    center = el.get("center")
    if center:
        return center["lat"], center["lon"]
    return None


def nearest(lat: float, lng: float, elements: list[dict]) -> tuple[float, dict] | None:
    """(distance_m, element) for the closest element, or None if the list is empty."""
    best: tuple[float, dict] | None = None
    for el in elements:
        point = coords(el)
        if point is None:
            continue
        d = haversine_m(lat, lng, point[0], point[1])
        if best is None or d < best[0]:
            best = (d, el)
    return best


def name(el: dict, fallback_keys: tuple[str, ...] = ()) -> str:
    tags = el.get("tags", {})
    for key in ("name", *fallback_keys):
        value = tags.get(key)
        if value:
            return value
    return "unnamed feature"
