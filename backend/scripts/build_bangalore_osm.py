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
import math
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
# service/overpass_categories.py, service/noise_sources.py, service/connectivity.py,
# service/daily_essentials.py and service/pollution_sources.py.
TAG_FILTERS = [
    "nwr/leisure=park",
    "nwr/landuse=forest,industrial,quarry,landfill",
    "nwr/natural=wood,water",
    "nwr/waterway=river,stream",
    "nwr/amenity=hospital,clinic,bar,nightclub,cafe,place_of_worship,school,pharmacy,bank,atm,"
    "marketplace,waste_disposal,waste_transfer_station",
    "nwr/shop=mall,supermarket,convenience,greengrocer",
    "nwr/highway=motorway,trunk,primary,bus_stop",
    "nwr/railway=station,halt,subway_entrance",
    "nwr/public_transport=station",
    "nwr/man_made=works,wastewater_plant",
    "nwr/aeroway=aerodrome",
]

# The exact (key, value) pairs the factors match on. osmium's tags-filter also pulls
# in nodes referenced by matched ways (so geometry stays valid), which drags along
# things like highway=crossing and landuse=basin - harmless at query time, but dead
# weight in the artifact, so features that don't carry one of these pairs are dropped.
TARGET_TAG_PAIRS = {
    # greenery / water
    ("leisure", "park"),
    ("landuse", "forest"),
    ("natural", "wood"),
    ("natural", "water"),
    ("waterway", "river"),
    ("waterway", "stream"),
    # healthcare / social / religious
    ("amenity", "hospital"),
    ("amenity", "clinic"),
    ("amenity", "bar"),
    ("amenity", "nightclub"),
    ("amenity", "cafe"),
    ("amenity", "place_of_worship"),
    ("shop", "mall"),
    # noise
    ("highway", "motorway"),
    ("highway", "trunk"),
    ("highway", "primary"),
    ("aeroway", "aerodrome"),
    # connectivity
    ("highway", "bus_stop"),
    ("railway", "station"),
    ("railway", "halt"),
    ("railway", "subway_entrance"),
    ("public_transport", "station"),
    # daily essentials
    ("amenity", "school"),
    ("amenity", "pharmacy"),
    ("amenity", "bank"),
    ("amenity", "atm"),
    ("amenity", "marketplace"),
    ("shop", "supermarket"),
    ("shop", "convenience"),
    ("shop", "greengrocer"),
    # pollution / odour
    ("landuse", "industrial"),
    ("landuse", "quarry"),
    ("landuse", "landfill"),
    ("man_made", "works"),
    ("man_made", "wastewater_plant"),
    ("amenity", "waste_disposal"),
    ("amenity", "waste_transfer_station"),
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
    "railway",
    "public_transport",
    "man_made",
    "station",  # distinguishes a metro station from a suburban rail one
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
            geometry = feature.get("geometry") or {}
            point = _representative_point(geometry)
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
            element = {"lat": round(lat, 6), "lon": round(lon, 6), "tags": tags}
            area = _polygon_area_m2(geometry)
            if area:
                element["area_m2"] = area
            elements.append(element)

    _share_areas_within_named_groups(elements)

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


# Same facility, mapped twice, close enough that it can only be one thing.
_AREA_SHARE_RADIUS_DEG = 0.005  # ~550m


def _share_areas_within_named_groups(elements: list[dict]) -> None:
    """Copies a known area onto co-located same-named features that lack one.

    OSM routinely carries one facility as both a node and a polygon - Cubbon Park's
    sewage plant is in here twice, once as a 6,243 m2 polygon and once as a bare
    point. Scoring reads whichever is nearest, so without this the size information
    the map actually has is thrown away half the time, and a shed-sized apartment
    plant gets penalised as though it were a municipal one.

    Matching is on name plus tags plus a ~550m radius, so the many genuinely distinct
    same-named features in a city (every "Reliance Fresh", every "Bus Stand") are
    never merged with each other.
    """
    groups: dict[tuple, list[dict]] = {}
    for el in elements:
        name = el["tags"].get("name")
        if not name:
            continue
        groups.setdefault((name, tuple(sorted(el["tags"].items()))), []).append(el)

    for members in groups.values():
        sized = [m for m in members if m.get("area_m2")]
        if not sized or len(sized) == len(members):
            continue
        for el in members:
            if el.get("area_m2"):
                continue
            near = [
                m
                for m in sized
                if abs(m["lat"] - el["lat"]) < _AREA_SHARE_RADIUS_DEG
                and abs(m["lon"] - el["lon"]) < _AREA_SHARE_RADIUS_DEG
            ]
            if near:
                el["area_m2"] = max(m["area_m2"] for m in near)


def _polygon_area_m2(geometry: dict) -> int | None:
    """Approximate ground area of a polygon feature, or None for points and lines.

    Footprint size is the only scale signal OSM reliably carries, and several factors
    need one: Bangalore mandates a sewage treatment plant in every apartment complex
    over a certain size, so `man_made=wastewater_plant` matches hundreds of shed-sized
    units that are not a nuisance at all alongside the handful of municipal plants
    that are. Without area, scoring treats them identically - see
    service/pollution_sources.py.

    Equirectangular projection around the polygon's own latitude, then the shoelace
    formula. Fine at these sizes; this is a threshold input, not a survey.
    """
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if not coords:
        return None
    if gtype == "Polygon":
        ring = coords[0] if coords else []
    elif gtype == "MultiPolygon":
        ring = coords[0][0] if coords and coords[0] else []
    else:
        return None
    if len(ring) < 4:
        return None

    lat0 = sum(p[1] for p in ring) / len(ring)
    m_per_deg_lat = 111_320.0
    m_per_deg_lng = 111_320.0 * math.cos(math.radians(lat0))
    xs = [p[0] * m_per_deg_lng for p in ring]
    ys = [p[1] * m_per_deg_lat for p in ring]
    total = 0.0
    for i in range(len(ring) - 1):
        total += xs[i] * ys[i + 1] - xs[i + 1] * ys[i]
    return int(abs(total) / 2.0) or None


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
