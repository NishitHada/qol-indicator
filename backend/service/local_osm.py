from __future__ import annotations

import gzip
import json
import math
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "bangalore_osm.json.gz"

_loaded = False
_bounds: dict[str, float] | None = None
# (tag key, tag value) -> elements carrying it, so a category lookup never scans the
# whole dataset.
_by_tag: dict[tuple[str, str], list[dict]] = {}


def _load() -> None:
    """Loads the bundled extract once. A missing file is not an error - the caller
    just falls back to querying Overpass over the network."""
    global _loaded, _bounds
    if _loaded:
        return
    _loaded = True
    if not DATA_PATH.exists():
        return
    with gzip.open(DATA_PATH, "rt", encoding="utf-8") as fh:
        payload = json.load(fh)
    _bounds = payload.get("bounds")
    for el in payload.get("elements", []):
        for key, value in el.get("tags", {}).items():
            _by_tag.setdefault((key, value), []).append(el)


def is_available() -> bool:
    _load()
    return _bounds is not None


def covers(lat: float, lng: float) -> bool:
    """True when the point is inside the bundled extract's area."""
    _load()
    if _bounds is None:
        return False
    return (
        _bounds["south"] <= lat <= _bounds["north"] and _bounds["west"] <= lng <= _bounds["east"]
    )


def elements_near(lat: float, lng: float, tags: list[tuple[str, str]], radius_m: float) -> list[dict]:
    """Elements matching any of `tags` within roughly `radius_m` of the point.

    Returns the same shape Overpass does ({"lat", "lon", "tags"}), so callers can feed
    the result through the same nearest/scoring path as the network response.

    The bounding-box prefilter is what keeps this fast: without it, a water lookup
    would run haversine against ~16k features on every request.
    """
    _load()
    dlat = radius_m / 111_320.0
    dlng = radius_m / (111_320.0 * max(0.01, math.cos(math.radians(lat))))

    out: list[dict] = []
    seen: set[int] = set()
    for pair in tags:
        for el in _by_tag.get(pair, ()):
            if id(el) in seen:
                continue
            if abs(el["lat"] - lat) > dlat or abs(el["lon"] - lng) > dlng:
                continue
            seen.add(id(el))
            out.append(el)
    return out
