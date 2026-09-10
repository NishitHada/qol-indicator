from __future__ import annotations

from domain.models import FactorStatus
from service import crowding, local_buildings

BLR_LAT, BLR_LNG = 12.9716, 77.6046


def test_bundled_grid_is_present_and_covers_bangalore():
    assert local_buildings.is_available(), (
        "bundled building grid missing - run scripts/build_bangalore_buildings.py"
    )
    assert local_buildings.covers(BLR_LAT, BLR_LNG)


def test_bounds_exclude_places_outside_the_grid():
    assert not local_buildings.covers(28.6139, 77.2090)  # Delhi
    assert local_buildings.sample(28.6139, 77.2090) is None


def test_no_cell_claims_more_building_than_ground():
    """Regression: assigning each footprint wholly to its centroid's cell produced a
    cell measuring 115% built coverage. Areas are now split across the cells a
    building's bounding box touches."""
    import gzip
    import json
    import math

    with gzip.open(local_buildings.DATA_PATH, "rt", encoding="utf-8") as fh:
        payload = json.load(fh)
    cell_deg = payload["cell_deg"]
    land = (cell_deg * 111_320.0) * (cell_deg * 111_320.0 * math.cos(math.radians(12.97)))
    worst = max(area / land for _, area, _ in payload["cells"].values())
    assert worst <= 1.0, f"a cell claims {worst:.0%} coverage"


def test_sample_reports_a_physically_possible_coverage():
    sample = local_buildings.sample(BLR_LAT, BLR_LNG)
    assert sample is not None
    assert sample.building_count > 0
    assert 0.0 <= sample.coverage_pct <= 100.0
    assert sample.buildings_per_hectare > 0


async def test_dense_core_scores_worse_than_a_low_density_layout():
    """Chickpet is one of the most crowded places in the city; Dollars Colony is a
    low-density bungalow layout. This is the ordering the factor exists to produce."""
    crowding._cache._store.clear()
    dense = await crowding.compute(12.9690, 77.5760)  # Chickpet
    crowding._cache._store.clear()
    spacious = await crowding.compute(13.0230, 77.5760)  # Dollars Colony

    assert dense.status == spacious.status == FactorStatus.OK
    assert spacious.score > dense.score
    assert spacious.raw_value < dense.raw_value  # less of the ground is built on


async def test_outside_the_bundle_is_unverified_not_a_guess():
    """There is no live vendor for this dataset, so outside the bundled area the
    factor must report NOT_FOUND and take the aggregator's floor rather than invent a
    score."""
    crowding._cache._store.clear()
    result = await crowding.compute(28.6139, 77.2090)  # Delhi
    assert result.status == FactorStatus.NOT_FOUND
    assert result.score is None


async def test_open_land_is_a_verified_hundred_not_a_failure():
    """This dataset is machine-extracted uniformly, so an empty area is evidence of
    open land rather than of nobody having mapped it - unlike OpenStreetMap, where the
    same emptiness would mean the opposite."""
    crowding._cache._store.clear()
    result = await crowding.compute(13.2400, 77.3400)
    assert result.status == FactorStatus.OK
    assert result.score == 100.0
    assert "open land" in result.detail


def test_score_curve_is_monotonic_between_its_anchors():
    scores = [crowding._score_from_coverage(c) for c in range(0, 101, 5)]
    assert scores == sorted(scores, reverse=True)
    assert crowding._score_from_coverage(crowding.GOOD_COVERAGE_PCT) == 100.0
    assert crowding._score_from_coverage(crowding.BAD_COVERAGE_PCT) == 0.0
