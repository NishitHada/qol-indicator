from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from dataclasses import dataclass

from domain.models import FactorResult, FactorStatus
from infra.cache import TTLCache
from infra.geo import haversine_m
from infra.http_client import get_client
from service import local_osm

# Ordered by measured responsiveness, not preference: z. consistently answers the same
# query in ~1s that the round-robin overpass-api.de entry point takes ~10s+ to answer
# (and often 504s outright). All three are the same public cluster and return
# identical data, so failing over between them costs nothing but a retry.
OVERPASS_MIRRORS = [
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
]
# The shared client's default 10s was cutting off responses that were about to
# succeed - these are heavy geo queries against a busy free service.
OVERPASS_TIMEOUT_S = 30.0

# Features are fetched and cached per ~550m grid cell rather than per clicked point,
# so clicking around a neighbourhood reuses one fetch instead of a request per click.
# Parks and lakes don't move; there's no reason to re-ask about them.
#
# The cell is deliberately small. An earlier attempt used ~5.5km tiles queried as a
# bbox expanded by each category's search radius, which ballooned the query to ~15km
# across (8x the area of the original per-point circle) and reliably 504'd on every
# mirror. Fetching a circle centred on the *cell centre* with radius
# (primary_radius + CELL_PADDING_M) keeps the query the same size as the original
# per-point one while still guaranteeing full coverage for any point in the cell.
CELL_DEG = 0.005
# Comfortably exceeds the half-diagonal of a CELL_DEG cell (~390m at these latitudes),
# so a point in any corner of the cell still sees everything within its full radius.
CELL_PADDING_M = 450


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
    # Narrows the matched features further than `tags` can. Applied after fetching, so
    # a filtered variant of a category still reuses the same cached elements rather
    # than issuing its own query - which matters because the filter is per-user (see
    # overpass_categories.for_profile) and the cache is not.
    element_filter: Callable[[dict], bool] | None = None
    # What the filter narrowed to, for the "nothing found" message. Without this a
    # Jain user searching a Hindu-majority area is told "no religious site nearby",
    # which is both wrong and unhelpful.
    subject: str | None = None

    def matching(self, elements: list[dict]) -> list[dict]:
        if self.element_filter is None:
            return elements
        return [el for el in elements if self.element_filter(el)]

    @property
    def described(self) -> str:
        return self.subject or self.label.lower()


# category key -> TTLCache of cell key -> raw element list
_element_caches: dict[str, TTLCache] = {}

# Cells whose fetch just failed, remembered briefly so a rate-limited category doesn't
# get re-hammered (and re-fail, slowly) on every subsequent click in the same area.
# Deliberately short: a 429 clears on its own, and we want to retry soon-ish - just
# not on every single click.
_failed_cells = TTLCache(ttl_seconds=60)


def _cache_for(category: ProximityCategory) -> TTLCache:
    cache = _element_caches.get(category.key)
    if cache is None:
        cache = TTLCache(ttl_seconds=category.cache_ttl_s)
        _element_caches[category.key] = cache
    return cache


def tile_key(lat: float, lng: float) -> str:
    south = math.floor(lat / CELL_DEG) * CELL_DEG
    west = math.floor(lng / CELL_DEG) * CELL_DEG
    return f"{south:.4f},{west:.4f}"


def _cell_center(lat: float, lng: float) -> tuple[float, float]:
    south = math.floor(lat / CELL_DEG) * CELL_DEG
    west = math.floor(lng / CELL_DEG) * CELL_DEG
    return south + CELL_DEG / 2, west + CELL_DEG / 2


def _tag_filter(key: str, values: list[str]) -> str:
    if len(values) == 1:
        return f'["{key}"="{values[0]}"]'
    # Multiple values sharing a key collapse into one regex clause instead of one
    # exact-match clause per value - this matters more now that several categories'
    # tags can end up in the same combined query.
    pattern = "^(" + "|".join(values) + ")$"
    return f'["{key}"~"{pattern}"]'


def _tags_by_key(cat: ProximityCategory) -> dict[str, list[str]]:
    by_key: dict[str, list[str]] = {}
    for k, v in cat.tags:
        by_key.setdefault(k, []).append(v)
    return by_key


def _build_cell_query(center_lat: float, center_lng: float, categories: list[ProximityCategory]) -> str:
    """One combined query covering every category, each at its own radius, centred on
    the grid cell rather than the clicked point so the result is reusable for any
    point in that cell."""
    clauses = []
    for cat in categories:
        radius = cat.primary_radius_m + CELL_PADDING_M
        for key, values in _tags_by_key(cat).items():
            filt = _tag_filter(key, values)
            clauses.append(f"node{filt}(around:{radius},{center_lat:.5f},{center_lng:.5f});")
            clauses.append(f"way{filt}(around:{radius},{center_lat:.5f},{center_lng:.5f});")
            clauses.append(f"relation{filt}(around:{radius},{center_lat:.5f},{center_lng:.5f});")
    body = "\n  ".join(clauses)
    return f"[out:json][timeout:25];\n(\n  {body}\n);\nout center 200;"


def _build_around_query(lat: float, lng: float, cat: ProximityCategory, radius_m: int) -> str:
    clauses = []
    for key, values in _tags_by_key(cat).items():
        filt = _tag_filter(key, values)
        clauses.append(f"node{filt}(around:{radius_m},{lat},{lng});")
        clauses.append(f"way{filt}(around:{radius_m},{lat},{lng});")
        clauses.append(f"relation{filt}(around:{radius_m},{lat},{lng});")
    body = "\n  ".join(clauses)
    return f"[out:json][timeout:25];\n(\n  {body}\n);\nout center 100;"


async def _post(query: str, preferred_mirror: int = 0) -> list[dict]:
    """Posts to each mirror in turn, returning the first successful response. Raises
    the last error only if every mirror failed.

    `preferred_mirror` rotates which mirror is tried first, so several categories
    resolved concurrently spread themselves across the cluster instead of all
    hammering the same server at once.
    """
    client = get_client()
    last_error: Exception | None = None
    count = len(OVERPASS_MIRRORS)
    for i in range(count):
        url = OVERPASS_MIRRORS[(preferred_mirror + i) % count]
        try:
            resp = await client.post(url, data={"data": query}, timeout=OVERPASS_TIMEOUT_S)
            resp.raise_for_status()
            return resp.json().get("elements", [])
        except Exception as e:  # noqa: PERF203 - trying the next mirror is the point
            last_error = e
    raise last_error if last_error else RuntimeError("no Overpass mirrors configured")


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
    return FactorResult(
        key=cat.key,
        label=cat.label,
        score=round(cat.score_fn(distance_m), 1),
        raw_value=round(distance_m, 1),
        unit="meters",
        status=FactorStatus.OK,
        source="osm-overpass",
        detail=f"{_feature_name(el, cat.name_tag_keys)}, {round(distance_m)}m",
    )


def _not_found_result(cat: ProximityCategory) -> FactorResult:
    return FactorResult(
        key=cat.key,
        label=cat.label,
        score=None,
        raw_value=None,
        unit=None,
        status=FactorStatus.NOT_FOUND,
        source="osm-overpass",
        detail=f"No {cat.described} found within {cat.fallback_radius_m}m",
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


async def _fetch_category(
    center_lat: float, center_lng: float, cat: ProximityCategory, mirror_index: int
) -> list[dict] | Exception:
    try:
        elements = await _post(_build_cell_query(center_lat, center_lng, [cat]), preferred_mirror=mirror_index)
        return [el for el in elements if _matches(el, cat.tags)]
    except Exception as e:
        return e


async def compute_categories(lat: float, lng: float, categories: list[ProximityCategory]) -> dict[str, FactorResult]:
    """Resolves multiple proximity categories for one point.

    Inside the bundled extract's area (see service/local_osm.py) this needs no network
    at all - the features are shipped with the app. That is the primary path: the
    public Overpass cluster refuses connections outright from cloud IPs, so relying on
    it in production meant these factors were permanently unverified. Static geography
    doesn't belong behind a live API anyway; parks and lakes don't move.

    Outside that area we fall back to Overpass, where features are cached per ~550m
    grid cell (so panning around a neighbourhood costs nothing after the first click)
    and uncached categories are fetched concurrently, one request each, spread across
    mirrors. One combined multi-category query was tried first and was consistently
    rejected (429) for being too heavy in a dense city.
    """
    results: dict[str, FactorResult] = {}
    cell = tile_key(lat, lng)
    elements_by_category: dict[str, list[dict]] = {}
    to_fetch: list[ProximityCategory] = []
    use_local = local_osm.covers(lat, lng)

    for cat in categories:
        if use_local:
            elements_by_category[cat.key] = local_osm.elements_near(lat, lng, cat.tags, cat.fallback_radius_m)
            continue
        cached = _cache_for(cat).get(cell)
        if cached is not None:
            elements_by_category[cat.key] = cached
        elif _failed_cells.get(f"{cat.key}@{cell}") is not None:
            results[cat.key] = _error_result(cat, RuntimeError("Overpass unavailable for this area, retrying shortly"))
        else:
            to_fetch.append(cat)

    if to_fetch:
        center_lat, center_lng = _cell_center(lat, lng)
        fetched = await asyncio.gather(
            *(_fetch_category(center_lat, center_lng, cat, i) for i, cat in enumerate(to_fetch))
        )
        for cat, outcome in zip(to_fetch, fetched, strict=True):
            if isinstance(outcome, Exception):
                _failed_cells.set(f"{cat.key}@{cell}", True)
                results[cat.key] = _error_result(cat, outcome)
            else:
                _cache_for(cat).set(cell, outcome)
                elements_by_category[cat.key] = outcome

    for cat in categories:
        if cat.key in results:  # errored above
            continue
        found = _nearest(lat, lng, cat.matching(elements_by_category.get(cat.key, [])))
        if found is None and not use_local:
            # Nothing in this cell's cached features - widen to a point-centred query
            # at this category's fallback radius before giving up. Skipped when the
            # answer came from the bundled extract, which is already complete for its
            # area: "nothing within the fallback radius" is a real answer there, not a
            # reason to spend 90s failing over mirrors.
            try:
                fallback_elements = await _post(_build_around_query(lat, lng, cat, cat.fallback_radius_m))
                found = _nearest(
                    lat, lng, cat.matching([el for el in fallback_elements if _matches(el, cat.tags)])
                )
            except Exception:
                found = None
        results[cat.key] = _to_result(cat, found) if found is not None else _not_found_result(cat)

    return results
