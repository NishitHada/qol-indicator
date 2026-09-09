from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from domain.models import FactorStatus
from service import greenery_water, overpass_batch


async def test_compute_greenery_found(monkeypatch):
    elements = [
        {"type": "node", "lat": 10.001, "lon": 20.0, "tags": {"leisure": "park", "name": "Test Park"}}
    ]
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"elements": elements})
    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(overpass_batch, "get_client", lambda: mock_client)
    overpass_batch._element_caches.clear()

    result = await greenery_water.compute_greenery(10.0, 20.0)

    assert result.status == FactorStatus.OK
    assert result.score > 0
    assert "Test Park" in result.detail


async def test_compute_greenery_not_found_scores_null_at_factor_level(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"elements": []})
    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(overpass_batch, "get_client", lambda: mock_client)
    overpass_batch._element_caches.clear()

    result = await greenery_water.compute_greenery(89.0, 179.0)

    assert result.status == FactorStatus.NOT_FOUND
    assert result.score is None


async def test_compute_water_found(monkeypatch):
    elements = [
        {"type": "way", "center": {"lat": 15.001, "lon": 25.0}, "tags": {"natural": "water", "name": "Test Lake"}}
    ]
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"elements": elements})
    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(overpass_batch, "get_client", lambda: mock_client)
    overpass_batch._element_caches.clear()

    result = await greenery_water.compute_water(15.0, 25.0)

    assert result.status == FactorStatus.OK
    assert "Test Lake" in result.detail
