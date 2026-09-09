#!/usr/bin/env python3
"""Builds the bundled Bangalore OSM feature file that service/local_osm.py reads.

Why this exists: the public Overpass API refuses connections outright from cloud
provider IPs (verified from Render), which meant greenery/water/healthcare/social/
religious factors were permanently "couldn't verify" in production while only the
Open-Meteo-backed factors worked. Parks and lakes don't move, so querying a live API
for them on every request was never the right design anyway.

This is a build-time script, not part of the runtime. It needs `osmium-tool`
(brew install osmium-tool); the runtime needs nothing but the stdlib and the JSON
artifact this produces.

Re-run it to refresh the data:

    python3 scripts/build_bangalore_osm.py
"""

from __future__ import annotations

import gzip
import json
import shutil
import subprocess
import sys
from pathlib import Path

SOURCE_URL = "https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf"
WORK_DIR = Path("/tmp/osmbuild")
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "bangalore_osm.json.gz"

# Generous bounds around the Bangalore metro - covers BBMP plus Kempegowda airport
# (13.199, 77.706) and the outer tech corridors.
SOUTH, WEST, NORTH, EAST = 12.70, 77.30, 13.25, 77.90

# Every tag the scoring factors actually look at. Keep in sync with
# service/overpass_categories.py and service/noise_sources.py.
TAG_FILTERS = [
    "nwr/leisure=park",
    "nwr/landuse=forest",
    "nwr/natural=wood,water",
    "nwr/waterway=river,stream",
    "nwr/amenity=hospital,clinic,bar,nightclub,cafe,place_of_worship",
    "nwr/shop=mall",
    "nwr/highway=motorway,trunk,primary",
    "nwr/aeroway=aerodrome",
]

# The exact (key, value) pairs the factors match on. osmium's tags-filter also pulls
# in nodes referenced by matched ways (so geometry stays valid), which drags along
# things like highway=crossing and landuse=basin - harmless at query time, but dead
# weight in the artifact, so features that don't carry one of these pairs are dropped.
TARGET_TAG_PAIRS = {
    ("leisure", "park"),
    ("landuse", "forest"),
    ("natural", "wood"),
    ("natural", "water"),
    ("waterway", "river"),
    ("waterway", "stream"),
    ("amenity", "hospital"),
    ("amenity", "clinic"),
    ("amenity", "bar"),
    ("amenity", "nightclub"),
    ("amenity", "cafe"),
    ("amenity", "place_of_worship"),
    ("shop", "mall"),
    ("highway", "motorway"),
    ("highway", "trunk"),
    ("highway", "primary"),
    ("aeroway", "aerodrome"),
}

# Only these tag keys are carried into the artifact - everything else is dead weight.
KEEP_TAG_KEYS = {
    "leisure",
    "landuse",
    "natural",
    "waterway",
    "amenity",
    "shop",
    "highway",
    "aeroway",
    "name",
    "religion",
    "denomination",
}


def run(cmd: list[str]) -> None:
    print(f"  $ {' '.join(cmd[:4])}{' ...' if len(cmd) > 4 else ''}", flush=True)
    subprocess.run(cmd, check=True)


def main() -> int:
    if shutil.which("osmium") is None:
        print("osmium-tool not found. Install it with: brew install osmium-tool", file=sys.stderr)
        return 1

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    source = WORK_DIR / "southern-zone.osm.pbf"
    if not source.exists():
        print(f"Source extract missing. Download it first:\n  curl -L -o {source} {SOURCE_URL}", file=sys.stderr)
        return 1

    clipped = WORK_DIR / "bangalore.osm.pbf"
    filtered = WORK_DIR / "bangalore-filtered.osm.pbf"
    exported = WORK_DIR / "bangalore.geojsonl"

    # The osmium steps are the slow part and their inputs rarely change, so they're
    # skipped when their output is already present. Pass --rebuild to force them.
    force = "--rebuild" in sys.argv

    print("1/4 clipping to the Bangalore bounding box")
    if force or not clipped.exists():
        run(
            ["osmium", "extract", "--overwrite", "--bbox", f"{WEST},{SOUTH},{EAST},{NORTH}", str(source), "-o", str(clipped)]
        )
    else:
        print("  (cached, pass --rebuild to redo)")

    print("2/4 filtering to the tags the scoring factors use")
    if force or not filtered.exists():
        run(["osmium", "tags-filter", "--overwrite", str(clipped), *TAG_FILTERS, "-o", str(filtered)])
    else:
        print("  (cached, pass --rebuild to redo)")

    print("3/4 exporting to GeoJSON with centroids")
    if force or not exported.exists():
        run(
            [
                "osmium",
                "export",
                "--overwrite",
                str(filtered),
                "-f",
                "geojsonseq",
                "--geometry-types=point,polygon,linestring",
                "-o",
                str(exported),
            ]
        )
    else:
        print("  (cached, pass --rebuild to redo)")

    print("4/4 converting to the runtime artifact")
    elements = []
    seen: set[tuple] = set()
    with exported.open() as fh:
        for line in fh:
            line = line.strip().lstrip("\x1e")  # geojsonseq record separator
            if not line:
                continue
            try:
                feature = json.loads(line)
            except json.JSONDecodeError:
                continue
            point = _representative_point(feature.get("geometry") or {})
            if point is None:
                continue
            props = feature.get("properties") or {}
            if not any((k, v) in TARGET_TAG_PAIRS for k, v in props.items()):
                continue
            tags = {k: v for k, v in props.items() if k in KEEP_TAG_KEYS}
            if not tags:
                continue
            lat, lon = point
            # OSM often carries the same feature as both a way and a relation; keeping
            # both just makes the nearest-lookup do the same work twice.
            fingerprint = (round(lat, 5), round(lon, 5), tags.get("name"), *sorted(tags.items())[:2])
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            elements.append({"lat": round(lat, 6), "lon": round(lon, 6), "tags": tags})

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "bounds": {"south": SOUTH, "west": WEST, "north": NORTH, "east": EAST},
        "source": SOURCE_URL,
        "elements": elements,
    }
    with gzip.open(OUTPUT, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))

    print(f"\nWrote {len(elements):,} features to {OUTPUT} ({OUTPUT.stat().st_size / 1_000_000:.1f} MB gzipped)")
    return 0


def _representative_point(geometry: dict) -> tuple[float, float] | None:
    """A single (lat, lon) standing in for the feature.

    This matches what Overpass's `out center` gave us - the centroid of a polygon or
    line - so scores stay comparable to the network-backed path. It is an
    approximation for large parks and long roads (the nearest *edge* can be much
    closer than the centre), same as before.
    """
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if not coords:
        return None
    if gtype == "Point":
        lon, lat = coords[0], coords[1]
        return lat, lon
    if gtype == "LineString":
        pts = coords
    elif gtype == "Polygon":
        pts = coords[0] if coords else []
    elif gtype == "MultiPolygon":
        pts = coords[0][0] if coords and coords[0] else []
    elif gtype == "MultiLineString":
        pts = coords[0] if coords else []
    else:
        return None
    if not pts:
        return None
    lons = [p[0] for p in pts if len(p) >= 2]
    lats = [p[1] for p in pts if len(p) >= 2]
    if not lats or not lons:
        return None
    return sum(lats) / len(lats), sum(lons) / len(lons)


if __name__ == "__main__":
    raise SystemExit(main())
