from __future__ import annotations

from domain.models import FactorStatus
from service import osm_lookup, pollution_sources

LAT, LNG = 12.9716, 77.6046


def _patch(monkeypatch, elements):
    async def _nearby(lat, lng, tags, radius_m):
        return [el for el in elements if osm_lookup.matches(el, tags)]

    monkeypatch.setattr(pollution_sources.osm_lookup, "nearby", _nearby)
    pollution_sources._cache._store.clear()


def _at(lat, lng, tags, area=None):
    el = {"lat": lat, "lon": lng, "tags": tags}
    if area:
        el["area_m2"] = area
    return el


async def test_nothing_nearby_is_a_verified_clean_reading(monkeypatch):
    """Absence is the good outcome here, as with noise. Returning NOT_FOUND would send
    it to the aggregator's floor and penalise exactly the locations that deserve the
    opposite."""
    _patch(monkeypatch, [])
    result = await pollution_sources.compute_pollution(LAT, LNG)
    assert result.status == FactorStatus.OK
    assert result.score == 100.0


async def test_adjacent_landfill_scores_far_worse_than_a_distant_one(monkeypatch):
    _patch(monkeypatch, [_at(LAT + 0.0005, LNG, {"landuse": "landfill"}, area=200_000)])
    close = await pollution_sources.compute_pollution(LAT, LNG)
    _patch(monkeypatch, [_at(LAT + 0.05, LNG, {"landuse": "landfill"}, area=200_000)])
    far = await pollution_sources.compute_pollution(LAT, LNG)
    assert close.score < 20.0
    assert far.score > close.score


async def test_a_small_mapped_plant_is_penalised_less_than_a_municipal_one(monkeypatch):
    """Bangalore mandates a sewage plant in every large apartment complex. Scoring a
    shed-sized one like a municipal plant put Cubbon Park at 53."""
    _patch(monkeypatch, [_at(LAT + 0.001, LNG, {"man_made": "wastewater_plant"}, area=6_000)])
    small = await pollution_sources.compute_pollution(LAT, LNG)
    _patch(monkeypatch, [_at(LAT + 0.001, LNG, {"man_made": "wastewater_plant"}, area=200_000)])
    municipal = await pollution_sources.compute_pollution(LAT, LNG)
    assert small.score > municipal.score


async def test_unmapped_area_is_treated_as_full_scale(monkeypatch):
    """Size only ever reduces a penalty, and only on proof. A source with no mapped
    footprint must score as though it were full-scale, so missing data can never talk
    the app into approving a location it should have flagged."""
    _patch(monkeypatch, [_at(LAT + 0.001, LNG, {"man_made": "wastewater_plant"})])
    unknown = await pollution_sources.compute_pollution(LAT, LNG)
    _patch(monkeypatch, [_at(LAT + 0.001, LNG, {"man_made": "wastewater_plant"}, area=500_000)])
    huge = await pollution_sources.compute_pollution(LAT, LNG)
    assert unknown.score == huge.score


async def test_worst_source_decides_not_the_nearest_one(monkeypatch):
    """A tiny plant next door is less of a problem than a large landfill down the road;
    picking the nearest feature first would decide the answer before scoring it."""
    _patch(
        monkeypatch,
        [
            _at(LAT, LNG, {"man_made": "wastewater_plant"}, area=1_000),
            _at(LAT + 0.004, LNG, {"landuse": "landfill"}, area=400_000),
        ],
    )
    result = await pollution_sources.compute_pollution(LAT, LNG)
    assert "landfill" in result.detail


async def test_odour_ignores_industry_but_not_sewage(monkeypatch):
    """An industrial estate degrades air quality without necessarily smelling."""
    _patch(monkeypatch, [_at(LAT, LNG, {"landuse": "industrial"}, area=100_000)])
    industrial = await pollution_sources.compute_odour(LAT, LNG)
    assert industrial.score == 100.0

    _patch(monkeypatch, [_at(LAT, LNG, {"man_made": "wastewater_plant"}, area=100_000)])
    sewage = await pollution_sources.compute_odour(LAT, LNG)
    assert sewage.score < 20.0


async def test_unnamed_feature_is_described_by_its_nuisance_type(monkeypatch):
    """A feature tagged both landuse=industrial and man_made=wastewater_plant was
    being reported as "industrial (sewage treatment plant)"."""
    _patch(monkeypatch, [_at(LAT, LNG, {"landuse": "industrial", "man_made": "wastewater_plant"})])
    result = await pollution_sources.compute_pollution(LAT, LNG)
    assert result.detail.startswith("sewage treatment plant,")


async def test_lookup_failure_is_an_error(monkeypatch):
    async def _boom(lat, lng, tags, radius_m):
        raise RuntimeError("down")

    monkeypatch.setattr(pollution_sources.osm_lookup, "nearby", _boom)
    pollution_sources._cache._store.clear()
    result = await pollution_sources.compute_pollution(LAT, LNG)
    assert result.status == FactorStatus.ERROR
    assert result.score is None
