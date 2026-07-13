from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from domain.models import FactorStatus
from service import greenery_water


def test_haversine_same_point_is_zero():
    assert greenery_water._haversine_m(0, 0, 0, 0) == 0


def test_score_from_distance_decay():
    assert greenery_water._score_from_distance(0, 500) == 100.0
    assert greenery_water._score_from_distance(500, 500) == pytest.approx(36.79, abs=0.1)


async def test_compute_greenery_found(monkeypatch):
    elements = [
        {"type": "node", "lat": 10.001, "lon": 20.0, "tags": {"leisure": "park", "name": "Test Park"}}
    ]
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"elements": elements})
    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(greenery_water, "get_client", lambda: mock_client)
    greenery_water._greenery_cache._store.clear()

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
    monkeypatch.setattr(greenery_water, "get_client", lambda: mock_client)
    greenery_water._greenery_cache._store.clear()

    result = await greenery_water.compute_greenery(89.0, 179.0)

    assert result.status == FactorStatus.NOT_FOUND
    assert result.score is None
