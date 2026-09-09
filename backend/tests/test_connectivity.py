from __future__ import annotations

from domain.models import FactorStatus
from service import connectivity, osm_lookup

BLR_LAT, BLR_LNG = 12.9716, 77.6046


def _fixed_elements(elements):
    async def _nearby(lat, lng, tags, radius_m):
        return [el for el in elements if osm_lookup.matches(el, tags)]

    return _nearby


def _patch(monkeypatch, elements):
    monkeypatch.setattr(connectivity.osm_lookup, "nearby", _fixed_elements(elements))
    connectivity._cache._store.clear()


async def test_metro_station_can_reach_full_marks(monkeypatch):
    _patch(
        monkeypatch,
        [{"lat": 12.9740, "lon": 77.6046, "tags": {"railway": "station", "station": "subway", "name": "Metro"}}],
    )
    result = await connectivity.compute(BLR_LAT, BLR_LNG)
    assert result.status == FactorStatus.OK
    assert result.score == 100.0
    assert "metro station" in result.detail


async def test_a_bus_stop_alone_is_capped_below_a_metro_station(monkeypatch):
    """The no-false-positives rule applied to transit: OSM records that a stop exists,
    not that it is usefully served, so a bus stop must not certify a location as
    well-connected however close it is."""
    _patch(monkeypatch, [{"lat": BLR_LAT, "lon": BLR_LNG, "tags": {"highway": "bus_stop", "name": "Stop"}}])
    on_top_of_it = await connectivity.compute(BLR_LAT, BLR_LNG)

    assert on_top_of_it.score == 65.0
    assert on_top_of_it.score < 100.0


async def test_best_mode_wins_rather_than_the_nearest_one(monkeypatch):
    """A metro station a walk away beats a bus stop at the door - averaging or taking
    the nearest would let the weaker mode decide."""
    _patch(
        monkeypatch,
        [
            {"lat": BLR_LAT, "lon": BLR_LNG, "tags": {"highway": "bus_stop", "name": "Doorstep Stop"}},
            {"lat": 12.9760, "lon": 77.6046, "tags": {"railway": "station", "station": "subway", "name": "Metro"}},
        ],
    )
    result = await connectivity.compute(BLR_LAT, BLR_LNG)
    assert "Metro" in result.detail
    assert result.score > 65.0


async def test_suburban_rail_is_not_counted_as_metro(monkeypatch):
    _patch(monkeypatch, [{"lat": BLR_LAT, "lon": BLR_LNG, "tags": {"railway": "station", "name": "Rail"}}])
    result = await connectivity.compute(BLR_LAT, BLR_LNG)
    assert result.score == 85.0
    assert "railway station" in result.detail


async def test_nothing_nearby_is_a_verified_zero_not_an_unverified_failure(monkeypatch):
    """Absence of transit is bad news, but it is a real finding - it must be reported
    as an OK zero so the aggregator scores it, not as NOT_FOUND."""
    _patch(monkeypatch, [])
    result = await connectivity.compute(BLR_LAT, BLR_LNG)
    assert result.status == FactorStatus.OK
    assert result.score == 0.0


async def test_lookup_failure_is_an_error_not_a_zero(monkeypatch):
    async def _boom(lat, lng, tags, radius_m):
        raise RuntimeError("overpass down")

    monkeypatch.setattr(connectivity.osm_lookup, "nearby", _boom)
    connectivity._cache._store.clear()
    result = await connectivity.compute(BLR_LAT, BLR_LNG)
    assert result.status == FactorStatus.ERROR
    assert result.score is None


async def test_real_bangalore_point_resolves_from_the_bundle_without_network():
    connectivity._cache._store.clear()
    result = await connectivity.compute(12.9784, 77.6408)  # Indiranagar metro
    assert result.status == FactorStatus.OK
    assert result.score is not None
