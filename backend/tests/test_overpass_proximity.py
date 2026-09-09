from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from domain.models import FactorStatus
from service import overpass_proximity


def _mock_client(elements=None, error=None):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"elements": elements or []})
    client = MagicMock()
    client.post = AsyncMock(side_effect=error) if error else AsyncMock(return_value=resp)
    return client


async def test_nearest_proximity_result_found(monkeypatch):
    elements = [{"type": "node", "lat": 1.001, "lon": 1.0, "tags": {"amenity": "hospital", "name": "City Hospital"}}]
    monkeypatch.setattr(overpass_proximity, "get_client", lambda: _mock_client(elements=elements))

    result = await overpass_proximity.nearest_proximity_result(
        1.0, 1.0, key="k", label="Healthcare", tags=[("amenity", "hospital")], decay_m=1000.0
    )

    assert result.status == FactorStatus.OK
    assert "City Hospital" in result.detail
    assert result.score is not None


async def test_nearest_proximity_result_not_found(monkeypatch):
    monkeypatch.setattr(overpass_proximity, "get_client", lambda: _mock_client(elements=[]))

    result = await overpass_proximity.nearest_proximity_result(
        1.0, 1.0, key="k", label="Healthcare", tags=[("amenity", "hospital")], decay_m=1000.0
    )

    assert result.status == FactorStatus.NOT_FOUND
    assert result.score is None


async def test_nearest_proximity_result_error(monkeypatch):
    monkeypatch.setattr(overpass_proximity, "get_client", lambda: _mock_client(error=RuntimeError("boom")))

    result = await overpass_proximity.nearest_proximity_result(
        1.0, 1.0, key="k", label="Healthcare", tags=[("amenity", "hospital")], decay_m=1000.0
    )

    assert result.status == FactorStatus.ERROR
    assert result.score is None


async def test_nearest_proximity_result_falls_back_to_wider_radius(monkeypatch):
    elements = [{"type": "node", "lat": 1.001, "lon": 1.0, "tags": {"amenity": "hospital", "name": "Far Hospital"}}]
    call_count = {"n": 0}

    async def fake_query(lat, lng, radius, tags):
        call_count["n"] += 1
        return [] if call_count["n"] == 1 else elements

    monkeypatch.setattr(overpass_proximity, "query_overpass", fake_query)

    result = await overpass_proximity.nearest_proximity_result(
        1.0,
        1.0,
        key="k",
        label="Healthcare",
        tags=[("amenity", "hospital")],
        decay_m=1000.0,
        primary_radius_m=100,
        fallback_radius_m=5000,
    )

    assert call_count["n"] == 2
    assert result.status == FactorStatus.OK
    assert "Far Hospital" in result.detail
