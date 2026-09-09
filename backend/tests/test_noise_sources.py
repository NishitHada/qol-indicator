from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from domain.models import FactorStatus
from service import noise_sources


def _mock_client(overpass_elements=None, adsb_aircraft=None, overpass_error=None, adsb_error=None):
    overpass_resp = MagicMock()
    overpass_resp.raise_for_status = MagicMock()
    overpass_resp.json = MagicMock(return_value={"elements": overpass_elements or []})

    adsb_resp = MagicMock()
    adsb_resp.raise_for_status = MagicMock()
    adsb_resp.json = MagicMock(return_value={"ac": adsb_aircraft or []})

    client = MagicMock()
    client.post = AsyncMock(side_effect=overpass_error) if overpass_error else AsyncMock(return_value=overpass_resp)
    client.get = AsyncMock(side_effect=adsb_error) if adsb_error else AsyncMock(return_value=adsb_resp)
    return client


async def test_compute_road_only(monkeypatch):
    elements = [
        {"type": "way", "tags": {"highway": "primary", "name": "MG Road"}, "center": {"lat": 12.9716, "lon": 77.5947}}
    ]
    client = _mock_client(overpass_elements=elements, adsb_aircraft=[])
    monkeypatch.setattr(noise_sources, "get_client", lambda: client)
    noise_sources._cache._store.clear()

    result = await noise_sources.compute(12.9716, 77.6047)

    assert result.status == FactorStatus.OK
    assert "MG Road" in result.detail
    assert result.score is not None


async def test_compute_close_road_scores_low_not_high(monkeypatch):
    # Regression: distance-decay direction is inverted for noise vs. greenery/water -
    # being CLOSE to a noise source must score LOW (loud), not high.
    elements = [
        {"type": "way", "tags": {"highway": "primary", "name": "Right Here Road"}, "center": {"lat": 5.0001, "lon": 5.0}}
    ]
    client = _mock_client(overpass_elements=elements, adsb_aircraft=[])
    monkeypatch.setattr(noise_sources, "get_client", lambda: client)
    noise_sources._cache._store.clear()

    result = await noise_sources.compute(5.0, 5.0)

    assert result.status == FactorStatus.OK
    assert result.score < 20.0


async def test_compute_combines_worst_of_road_and_airport(monkeypatch):
    elements = [
        {"type": "way", "tags": {"highway": "primary", "name": "Far Road"}, "center": {"lat": 12.99, "lon": 77.62}},
        {
            "type": "way",
            "tags": {"aeroway": "aerodrome", "name": "Close Airport"},
            "center": {"lat": 12.9717, "lon": 77.5948},
        },
    ]
    client = _mock_client(overpass_elements=elements, adsb_aircraft=[])
    monkeypatch.setattr(noise_sources, "get_client", lambda: client)
    noise_sources._cache._store.clear()

    result = await noise_sources.compute(12.9716, 77.5947)

    assert result.status == FactorStatus.OK
    assert "Close Airport" in result.detail


async def test_compute_low_altitude_flight_can_only_worsen_score(monkeypatch):
    elements = []  # no structural sources at all
    aircraft = [{"flight": "TEST123", "alt_baro": 2000, "dst": 1.0}]  # ~1852m away, low altitude
    client = _mock_client(overpass_elements=elements, adsb_aircraft=aircraft)
    monkeypatch.setattr(noise_sources, "get_client", lambda: client)
    noise_sources._cache._store.clear()

    result = await noise_sources.compute(12.9716, 77.5947)

    assert result.status == FactorStatus.OK
    assert "TEST123" in result.detail


async def test_compute_ignores_high_altitude_flights(monkeypatch):
    aircraft = [{"flight": "CRUISE1", "alt_baro": 35000, "dst": 0.5}]
    client = _mock_client(overpass_elements=[], adsb_aircraft=aircraft)
    monkeypatch.setattr(noise_sources, "get_client", lambda: client)
    noise_sources._cache._store.clear()

    result = await noise_sources.compute(12.9716, 77.5947)

    # A cruise-altitude flight isn't a candidate, so with nothing else nearby this is
    # a confirmed-quiet OK result, not a NOT_FOUND (which would wrongly get floored
    # low by the aggregator - absence of noise sources is the *good* outcome here).
    assert result.status == FactorStatus.OK
    assert result.score == 100.0


async def test_compute_confirmed_quiet_when_nothing_nearby(monkeypatch):
    client = _mock_client(overpass_elements=[], adsb_aircraft=[])
    monkeypatch.setattr(noise_sources, "get_client", lambda: client)
    noise_sources._cache._store.clear()

    result = await noise_sources.compute(1.0, 1.0)

    assert result.status == FactorStatus.OK
    assert result.score == 100.0


async def test_compute_overpass_failure_is_error(monkeypatch):
    client = _mock_client(overpass_error=RuntimeError("boom"))
    monkeypatch.setattr(noise_sources, "get_client", lambda: client)
    noise_sources._cache._store.clear()

    result = await noise_sources.compute(2.0, 2.0)

    assert result.status == FactorStatus.ERROR
    assert result.score is None


async def test_compute_flight_lookup_failure_does_not_invalidate_structural_result(monkeypatch):
    elements = [
        {"type": "way", "tags": {"highway": "primary", "name": "Still Works Road"}, "center": {"lat": 3.001, "lon": 3.0}}
    ]
    client = _mock_client(overpass_elements=elements, adsb_error=RuntimeError("adsb down"))
    monkeypatch.setattr(noise_sources, "get_client", lambda: client)
    noise_sources._cache._store.clear()

    result = await noise_sources.compute(3.0, 3.0)

    assert result.status == FactorStatus.OK
    assert "Still Works Road" in result.detail
