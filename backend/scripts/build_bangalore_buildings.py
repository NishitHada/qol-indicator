#!/usr/bin/env python3
"""Builds the bundled Bangalore building-density grid that service/local_buildings.py reads.

Source: Microsoft's Global ML Building Footprints (ODbL, commercial use permitted),
machine-extracted from satellite imagery and refreshed periodically. We use it rather
than OpenStreetMap's own buildings for one specific reason: OSM building detail tracks
how much mapping effort an area has received, and mapping effort correlates with
affluence, so OSM building statistics are biased in exactly the direction that would
matter here. Measured over the same bounding box, OSM has 819,228 buildings in 21,290
occupied cells; this dataset has 1,030,477 in 45,027. The doubled cell count is the
part that matters - those are areas OSM simply has not mapped.

Google Earth / Maps imagery cannot be used for this. It is licensed from Maxar, Airbus
and CNES, and the Maps Platform terms prohibit bulk download, derived datasets, and
training models on the content. This dataset is the same extraction already done and
published under a licence that permits it.

What gets stored is per-cell *measurements* - building count, summed footprint area,
median footprint - not scores. Scoring thresholds live in service/crowding.py, so
changing a threshold does not require rebuilding this file. Same contract as the OSM
and climate bundles.

This is a build-time script. It downloads roughly 110 MB of tiles:

    python3 scripts/build_bangalore_buildings.py
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import math
import statistics
import urllib.request
from pathlib import Path

LINKS_URL = "https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv"
REGION = "India"
WORK_DIR = Path("/tmp/msbuild")
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "bangalore_buildings.json.gz"

# Same bounds as the other two bundles, so all three cover the same area.
SOUTH, WEST, NORTH, EAST = 12.70, 77.30, 13.25, 77.90

# ~220m at this latitude. Small enough that a cell describes one block rather than a
# whole neighbourhood; large enough that a typical urban cell holds tens of buildings,
# so the statistics mean something. The factor samples a 3x3 block of these.
CELL_DEG = 0.002

# The dataset is tiled by Bing quadkey at zoom 9.
QUADKEY_ZOOM = 9


def quadkey(lat: float, lng: float, zoom: int) -> str:
    sin_lat = math.sin(math.radians(lat))
    x = int(((lng + 180) / 360) * (1 << zoom))
    y = int((0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * (1 << zoom))
    key = ""
    for i in range(zoom, 0, -1):
        digit = 0
        mask = 1 << (i - 1)
        if x & mask:
            digit += 1
        if y & mask:
            digit += 2
        key += str(digit)
    return key


def covering_quadkeys() -> set[str]:
    """Every zoom-9 tile the bounding box touches, found by walking its edges rather
    than only its corners - a tile can be crossed without containing a corner."""
    keys = set()
    lat = SOUTH
    while lat <= NORTH + 1e-9:
        lng = WEST
        while lng <= EAST + 1e-9:
            keys.add(quadkey(lat, lng, QUADKEY_ZOOM))
            lng += 0.05
        lat += 0.05
    return keys


def tile_urls() -> list[str]:
    print("1/3 finding the tiles that cover Bangalore")
    with urllib.request.urlopen(LINKS_URL, timeout=180) as resp:  # noqa: S310 - fixed https host
        rows = list(csv.DictReader(io.TextIOWrapper(resp, encoding="utf-8")))
    wanted = covering_quadkeys()
    urls = [r["Url"] for r in rows if r["Location"] == REGION and r["QuadKey"] in wanted]
    print(f"  {len(urls)} tiles")
    return urls


def download(urls: list[str]) -> list[Path]:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    print("2/3 downloading tiles")
    for i, url in enumerate(urls, 1):
        path = WORK_DIR / f"tile{i}.csv.gz"
        if not path.exists():
            print(f"  {i}/{len(urls)} {url.rsplit('/', 1)[-1][:40]}", flush=True)
            urllib.request.urlretrieve(url, path)  # noqa: S310 - url comes from the fixed manifest
        paths.append(path)
    return paths


def _ring_metrics(ring: list) -> tuple[float, float, float, float, float, float, float] | None:
    """(area_m2, centroid_lat, centroid_lng, south, west, north, east) for one ring."""
    if len(ring) < 4:
        return None
    lats = [p[1] for p in ring]
    lngs = [p[0] for p in ring]
    lat0 = sum(lats) / len(lats)
    lng0 = sum(lngs) / len(lngs)
    m_per_deg_lng = 111_320.0 * math.cos(math.radians(lat0))
    m_per_deg_lat = 111_320.0
    total = 0.0
    for i in range(len(ring) - 1):
        total += (ring[i][0] * m_per_deg_lng) * (ring[i + 1][1] * m_per_deg_lat)
        total -= (ring[i + 1][0] * m_per_deg_lng) * (ring[i][1] * m_per_deg_lat)
    return abs(total) / 2.0, lat0, lng0, min(lats), min(lngs), max(lats), max(lngs)


def _apportion(area_m2: float, south: float, west: float, north: float, east: float) -> dict[tuple[int, int], float]:
    """Splits a building's footprint across every cell its bounding box touches.

    Assigning the whole footprint to the centroid's cell is what produced a cell
    measuring 115% built coverage in testing - impossible, and caused by a handful of
    buildings larger than a cell. Splitting by the share of the bounding box that falls
    in each cell is approximate but removes that artifact, and for the vast majority of
    buildings it is exact anyway: the median footprint is 113 m2 against a cell of
    roughly 48,000 m2, so almost every building lies wholly inside one cell.
    """
    i0, i1 = math.floor(south / CELL_DEG), math.floor(north / CELL_DEG)
    j0, j1 = math.floor(west / CELL_DEG), math.floor(east / CELL_DEG)
    if i0 == i1 and j0 == j1:
        return {(i0, j0): area_m2}

    box_h = max(north - south, 1e-12)
    box_w = max(east - west, 1e-12)
    shares: dict[tuple[int, int], float] = {}
    for i in range(i0, i1 + 1):
        lat_lo = max(south, i * CELL_DEG)
        lat_hi = min(north, (i + 1) * CELL_DEG)
        if lat_hi <= lat_lo:
            continue
        for j in range(j0, j1 + 1):
            lng_lo = max(west, j * CELL_DEG)
            lng_hi = min(east, (j + 1) * CELL_DEG)
            if lng_hi <= lng_lo:
                continue
            shares[(i, j)] = area_m2 * ((lat_hi - lat_lo) / box_h) * ((lng_hi - lng_lo) / box_w)
    return shares or {(i0, j0): area_m2}


def main() -> int:
    paths = download(tile_urls())

    print("3/3 aggregating footprints into the grid")
    built_area: dict[tuple[int, int], float] = {}
    footprints: dict[tuple[int, int], list[float]] = {}
    read = 0
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                read += 1
                try:
                    feature = json.loads(line)
                except json.JSONDecodeError:
                    continue
                coords = (feature.get("geometry") or {}).get("coordinates")
                if not coords:
                    continue
                metrics = _ring_metrics(coords[0])
                if metrics is None:
                    continue
                area, lat0, lng0, south, west, north, east = metrics
                if area <= 1 or not (SOUTH <= lat0 <= NORTH and WEST <= lng0 <= EAST):
                    continue
                # Count and median footprint go to the centroid's cell - a building's
                # size belongs where the building is. Only the summed built *area* is
                # apportioned, because that is the one used as a ratio of land area.
                footprints.setdefault((math.floor(lat0 / CELL_DEG), math.floor(lng0 / CELL_DEG)), []).append(area)
                for cell, share in _apportion(area, south, west, north, east).items():
                    built_area[cell] = built_area.get(cell, 0.0) + share

    cells = {}
    for cell, areas in footprints.items():
        i, j = cell
        cells[f"{i},{j}"] = [
            len(areas),
            round(built_area.get(cell, 0.0)),
            round(statistics.median(areas), 1),
        ]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUTPUT, "wt", encoding="utf-8") as fh:
        json.dump(
            {
                "bounds": {"south": SOUTH, "west": WEST, "north": NORTH, "east": EAST},
                "cell_deg": CELL_DEG,
                "source": "Microsoft Global ML Building Footprints (ODbL)",
                # [building count, summed footprint m2, median footprint m2] per cell.
                "cells": cells,
            },
            fh,
            separators=(",", ":"),
        )

    total = sum(len(a) for a in footprints.values())
    print(
        f"\nRead {read:,} features, kept {total:,} inside the bounds, "
        f"{len(cells):,} cells -> {OUTPUT} ({OUTPUT.stat().st_size / 1_000_000:.2f} MB gzipped)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
