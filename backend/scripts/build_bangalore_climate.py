#!/usr/bin/env python3
"""Builds the bundled Bangalore climate grid that service/local_climate.py reads.

Carries daily temperature (max/min/mean) and daily wind (peak speed, dominant
direction) for every grid point, feeding service/temperature.py and
service/wind_ventilation.py respectively.

Why this exists: Open-Meteo's archive API (ERA5) rate-limits Render's shared outbound
IP with a 429, while the identical request succeeds from a normal machine - so the
temperature factor was permanently failing in production. Same root problem as the
Overpass one, and the same fix: a location's 365-day temperature profile barely moves
year to year, so it doesn't belong behind a per-request network call.

Stores the raw daily series rather than a precomputed score, so all the aggregation
and scoring stays in service/temperature.py - one code path for both the bundled and
the network case. Changing the comfort band or extreme-day thresholds therefore does
NOT require rebuilding this file.

This is a build-time script. Run it from a machine that isn't rate-limited:

    python3 scripts/build_bangalore_climate.py
"""

from __future__ import annotations

import gzip
import json
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "bangalore_climate.json.gz"

# Same bounds as the OSM extract, so the two bundled datasets cover the same area.
SOUTH, WEST, NORTH, EAST = 12.70, 77.30, 13.25, 77.90

# 0.1 degrees (~11km). Deliberately aligned with the factor's cache-key precision, and
# still finer than ERA5's own ~25km grid - the API visibly snaps requested points to
# its own grid, so a denser sampling would buy nothing.
GRID_DEG = 0.1

ARCHIVE_LAG_DAYS = 2
WINDOW_DAYS = 365


def grid_points() -> list[tuple[float, float]]:
    points = []
    lat = SOUTH
    while lat <= NORTH + 1e-9:
        lng = WEST
        while lng <= EAST + 1e-9:
            points.append((round(lat, 1), round(lng, 1)))
            lng += GRID_DEG
        lat += GRID_DEG
    return points


def main() -> int:
    end_date = date.today() - timedelta(days=ARCHIVE_LAG_DAYS)
    start_date = end_date - timedelta(days=WINDOW_DAYS)
    points = grid_points()
    print(f"Fetching {len(points)} grid points, {start_date} to {end_date}")

    query = urllib.parse.urlencode(
        {
            "latitude": ",".join(str(p[0]) for p in points),
            "longitude": ",".join(str(p[1]) for p in points),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "daily": "temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
            "wind_speed_10m_max,wind_direction_10m_dominant",
            "timezone": "auto",
        }
    )
    with urllib.request.urlopen(f"{ARCHIVE_URL}?{query}", timeout=180) as resp:  # noqa: S310 - fixed https host
        payload = json.load(resp)

    if isinstance(payload, dict):  # single-location responses aren't wrapped in a list
        payload = [payload]
    if len(payload) != len(points):
        print(f"warning: asked for {len(points)} points, got {len(payload)} back")

    grid: dict[str, dict[str, list[float | None]]] = {}
    for (lat, lng), loc in zip(points, payload, strict=False):
        daily = loc.get("daily") or {}
        series = {
            "max": _round_all(daily.get("temperature_2m_max")),
            "min": _round_all(daily.get("temperature_2m_min")),
            "mean": _round_all(daily.get("temperature_2m_mean")),
            # Daily peak wind and its dominant direction, for the cross-ventilation
            # factor. Direction is kept per-day rather than averaged at build time -
            # the factor measures how much the direction *varies* over the year, which
            # an average would destroy.
            "wind_speed": _round_all(daily.get("wind_speed_10m_max")),
            "wind_dir": _round_all(daily.get("wind_direction_10m_dominant")),
        }
        if not series["mean"]:
            print(f"  skipping {lat},{lng} - no data returned")
            continue
        grid[f"{lat},{lng}"] = series

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUTPUT, "wt", encoding="utf-8") as fh:
        json.dump(
            {
                "bounds": {"south": SOUTH, "west": WEST, "north": NORTH, "east": EAST},
                "grid_deg": GRID_DEG,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "points": grid,
            },
            fh,
            separators=(",", ":"),
        )

    days = len(next(iter(grid.values()))["mean"]) if grid else 0
    print(f"\nWrote {len(grid)} grid points x {days} days to {OUTPUT} ({OUTPUT.stat().st_size / 1_000_000:.2f} MB gzipped)")
    return 0


def _round_all(values: list | None) -> list[float | None]:
    if not values:
        return []
    return [round(v, 1) if isinstance(v, (int, float)) else None for v in values]


if __name__ == "__main__":
    raise SystemExit(main())
