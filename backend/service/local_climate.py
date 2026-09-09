from __future__ import annotations

import gzip
import json
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "bangalore_climate.json.gz"

_loaded = False
_bounds: dict[str, float] | None = None
_grid_deg = 0.1
_points: dict[str, dict[str, list]] = {}


def _load() -> None:
    """Loads the bundled climate grid once. A missing file is not an error - the
    caller just falls back to querying Open-Meteo over the network."""
    global _loaded, _bounds, _grid_deg
    if _loaded:
        return
    _loaded = True
    if not DATA_PATH.exists():
        return
    with gzip.open(DATA_PATH, "rt", encoding="utf-8") as fh:
        payload = json.load(fh)
    _bounds = payload.get("bounds")
    _grid_deg = payload.get("grid_deg", 0.1)
    _points.update(payload.get("points", {}))


def is_available() -> bool:
    _load()
    return _bounds is not None and bool(_points)


def covers(lat: float, lng: float) -> bool:
    _load()
    if _bounds is None or not _points:
        return False
    return _bounds["south"] <= lat <= _bounds["north"] and _bounds["west"] <= lng <= _bounds["east"]


def _series_at(lat: float, lng: float) -> dict[str, list] | None:
    _load()
    if not covers(lat, lng):
        return None
    key = f"{round(lat / _grid_deg) * _grid_deg:.1f},{round(lng / _grid_deg) * _grid_deg:.1f}"
    series = _points.get(key)
    if series is None:
        # Point is inside the bounds but the grid cell has no data (edge of the box);
        # fall back to whichever cell is genuinely nearest.
        series = _nearest_point(lat, lng)
    return series


def daily_series(lat: float, lng: float) -> tuple[list, list, list] | None:
    """Daily (max, min, mean) temperature series for the nearest grid point.

    Returns the same shape the Open-Meteo archive response gives, so the caller can
    run the identical aggregation and scoring over either source.
    """
    series = _series_at(lat, lng)
    if series is None:
        return None
    return series["max"], series["min"], series["mean"]


def wind_series(lat: float, lng: float) -> tuple[list, list] | None:
    """Daily (peak speed km/h, dominant direction degrees) for the nearest grid point.

    Returns None when the bundle predates the wind fields, so an older artifact keeps
    serving temperature rather than breaking the whole request.
    """
    series = _series_at(lat, lng)
    if series is None or not series.get("wind_speed") or not series.get("wind_dir"):
        return None
    return series["wind_speed"], series["wind_dir"]


def _nearest_point(lat: float, lng: float) -> dict[str, list] | None:
    best = None
    best_d2 = None
    for key, series in _points.items():
        plat, plng = (float(x) for x in key.split(","))
        d2 = (plat - lat) ** 2 + (plng - lng) ** 2
        if best_d2 is None or d2 < best_d2:
            best_d2 = d2
            best = series
    return best
