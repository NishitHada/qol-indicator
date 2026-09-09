from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from domain.models import FactorResult, FactorStatus
from infra.cache import TTLCache, geo_cache_key
from infra.geo import haversine_m
from infra.http_client import get_client

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


@dataclass(frozen=True)
class ProximityCategory:
    key: str
    label: str
    tags: list[tuple[str, str]]
    score_fn: Callable[[float], float]
    primary_radius_m: int = 3000
    fallback_radius_m: int = 8000
    name_tag_keys: tuple[str, ...] = ("name",)
    cache_ttl_s: float = 86400


_caches: dict[str, TTLCache] = {}


def _cache_for(category: ProximityCategory) -> TTLCache:
    cache = _caches.get(category.key)
    if cache is None:
        cache = TTLCache(ttl_seconds=category.cache_ttl_s)
        _caches[category.key] = cache
    return cache


def _tag_filter(key: str, values: list[str]) -> str:
    if len(values) == 1:
        return f'["{key}"="{values[0]}"]'
    # Multiple values sharing a key collapse into one regex clause instead of one
    # exact-match clause per value - this matters more now that several categories'
    # tags can end up in the same combined query.
    pattern = "^(" + "|".join(values) + ")$"
    return f'["{key}"~"{pattern}"]'


def _build_query(lat: float, lng: float, categories_with_radius: list[tuple[ProximityCategory, int]]) -> str:
    clauses = []
    for cat, radius in categories_with_radius:
        by_key: dict[str, list[str]] = {}
        for k, v in cat.tags:
            by_key.setdefault(k, []).append(v)
        for key, values in by_key.items():
            filt = _tag_filter(key, values)
            clauses.append(f"node{filt}(around:{radius},{lat},{lng});")
            clauses.append(f"way{filt}(around:{radius},{lat},{lng});")
            clauses.append(f"relation{filt}(around:{radius},{lat},{lng});")
    body = "\n  ".join(clauses)
    # A generous result cap: this query can cover several categories at once, so the
    # cap needs enough headroom that a dense category (e.g. cafes) can't starve a
    # sparser one (e.g. hospitals) of its share of the result set.
    return f"[out:json][timeout:20];\n(\n  {body}\n);\nout center 200;"


async def _query(lat: float, lng: float, categories_with_radius: list[tuple[ProximityCategory, int]]) -> list[dict]:
    client = get_client()
    query = _build_query(lat, lng, categories_with_radius)
    resp = await client.post(OVERPASS_URL, data={"data": query})
    resp.raise_for_status()
    return resp.json().get("elements", [])


def _element_coords(el: dict) -> tuple[float, float] | None:
    if "lat" in el and "lon" in el:
        return el["lat"], el["lon"]
    center = el.get("center")
    if center:
        return center["lat"], center["lon"]
    return None


def _matches(el: dict, tags: list[tuple[str, str]]) -> bool:
    el_tags = el.get("tags", {})
    return any(el_tags.get(k) == v for k, v in tags)


def _nearest(lat: float, lng: float, elements: list[dict]) -> tuple[float, dict] | None:
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


def _feature_name(el: dict, name_tag_keys: tuple[str, ...]) -> str:
    tags = el.get("tags", {})
    for k in name_tag_keys:
        v = tags.get(k)
        if v:
            return v
    return "unnamed feature"


def _to_result(cat: ProximityCategory, found: tuple[float, dict]) -> FactorResult:
    distance_m, el = found
    score = cat.score_fn(distance_m)
    return FactorResult(
        key=cat.key,
        label=cat.label,
        score=round(score, 1),
        raw_value=round(distance_m, 1),
        unit="meters",
        status=FactorStatus.OK,
        source="osm-overpass",
        detail=f"{_feature_name(el, cat.name_tag_keys)}, {round(distance_m)}m",
    )


def _not_found_result(cat: ProximityCategory, radius_used: int) -> FactorResult:
    return FactorResult(
        key=cat.key,
        label=cat.label,
        score=None,
        raw_value=None,
        unit=None,
        status=FactorStatus.NOT_FOUND,
        source="osm-overpass",
        detail=f"No {cat.label.lower()} found within {radius_used}m",
    )


def _error_result(cat: ProximityCategory, error: Exception) -> FactorResult:
    return FactorResult(
        key=cat.key,
        label=cat.label,
        score=None,
        raw_value=None,
        unit=None,
        status=FactorStatus.ERROR,
        detail=f"Overpass request failed: {error}",
    )


async def compute_categories(lat: float, lng: float, categories: list[ProximityCategory]) -> dict[str, FactorResult]:
    """Resolves multiple proximity categories for one location, batching them into as
    few Overpass HTTP calls as possible: one call covers every category not already
    cached, at each category's own primary radius; a second call (only if needed)
    covers whichever categories came back empty, at their own fallback radius.

    Passing several categories together is the whole point of this function - each
    call to compute_categories with a single category still works correctly, but
    callers wanting the batching benefit should pass as many categories as they can
    resolve at once (see service/aggregator.py for how the v1 registry does this).
    """
    results: dict[str, FactorResult] = {}
    to_fetch: list[ProximityCategory] = []
    cache_key = geo_cache_key(lat, lng)

    for cat in categories:
        cached = _cache_for(cat).get(cache_key)
        if cached is not None:
            results[cat.key] = cached
        else:
            to_fetch.append(cat)

    if not to_fetch:
        return results

    try:
        elements = await _query(lat, lng, [(cat, cat.primary_radius_m) for cat in to_fetch])
    except Exception as e:
        for cat in to_fetch:
            results[cat.key] = _error_result(cat, e)
        return results

    missing: list[ProximityCategory] = []
    for cat in to_fetch:
        matched = [el for el in elements if _matches(el, cat.tags)]
        found = _nearest(lat, lng, matched)
        if found is None:
            missing.append(cat)
        else:
            result = _to_result(cat, found)
            _cache_for(cat).set(cache_key, result)
            results[cat.key] = result

    if missing:
        try:
            fallback_elements = await _query(lat, lng, [(cat, cat.fallback_radius_m) for cat in missing])
        except Exception:
            fallback_elements = []
        for cat in missing:
            matched = [el for el in fallback_elements if _matches(el, cat.tags)]
            found = _nearest(lat, lng, matched)
            result = _to_result(cat, found) if found is not None else _not_found_result(cat, cat.fallback_radius_m)
            _cache_for(cat).set(cache_key, result)
            results[cat.key] = result

    return results
