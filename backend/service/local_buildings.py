from __future__ import annotations

import gzip
import json
import math
from dataclasses import dataclass
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "bangalore_buildings.json.gz"

_loaded = False
_bounds: dict[str, float] | None = None
_cell_deg = 0.002
# "i,j" -> [building count, summed footprint m2, median footprint m2]
_cells: dict[str, list[float]] = {}


@dataclass(frozen=True)
class BuildingSample:
    """Aggregate built form over a square of cells around a point."""

    building_count: int
    built_area_m2: float
    land_area_m2: float
    typical_footprint_m2: float

    @property
    def coverage_pct(self) -> float:
        """Share of the ground covered by building footprints, 0-100."""
        if self.land_area_m2 <= 0:
            return 0.0
        return 100.0 * self.built_area_m2 / self.land_area_m2

    @property
    def buildings_per_hectare(self) -> float:
        if self.land_area_m2 <= 0:
            return 0.0
        return self.building_count / (self.land_area_m2 / 10_000.0)


def _load() -> None:
    """Loads the bundled grid once. A missing file is not an error - the caller
    reports the factor as unverified rather than failing the whole request."""
    global _loaded, _bounds, _cell_deg
    if _loaded:
        return
    _loaded = True
    if not DATA_PATH.exists():
        return
    with gzip.open(DATA_PATH, "rt", encoding="utf-8") as fh:
        payload = json.load(fh)
    _bounds = payload.get("bounds")
    _cell_deg = payload.get("cell_deg", 0.002)
    _cells.update(payload.get("cells", {}))


def is_available() -> bool:
    _load()
    return _bounds is not None and bool(_cells)


def covers(lat: float, lng: float) -> bool:
    _load()
    if _bounds is None or not _cells:
        return False
    return _bounds["south"] <= lat <= _bounds["north"] and _bounds["west"] <= lng <= _bounds["east"]


def sample(lat: float, lng: float, radius_cells: int = 1) -> BuildingSample | None:
    """Built form in the square of cells centred on the point.

    There is no network fallback: the source is a bulk tile download, not an API, so
    outside the bundled area this returns None and the factor reports itself
    unverified. That is the honest answer - we would rather say nothing than guess.
    """
    _load()
    if not covers(lat, lng):
        return None

    ci = math.floor(lat / _cell_deg)
    cj = math.floor(lng / _cell_deg)
    count = 0
    built = 0.0
    weighted_footprint = 0.0
    for i in range(ci - radius_cells, ci + radius_cells + 1):
        for j in range(cj - radius_cells, cj + radius_cells + 1):
            cell = _cells.get(f"{i},{j}")
            if cell is None:
                continue
            n, area, median = cell
            count += int(n)
            built += area
            weighted_footprint += median * n

    side_deg = (2 * radius_cells + 1) * _cell_deg
    land = (side_deg * 111_320.0) * (side_deg * 111_320.0 * math.cos(math.radians(lat)))
    typical = weighted_footprint / count if count else 0.0
    return BuildingSample(
        building_count=count,
        built_area_m2=built,
        land_area_m2=land,
        typical_footprint_m2=typical,
    )
