from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from domain.models import FactorStatus
from service import air_quality


def test_score_from_aqi_breakpoints():
    assert air_quality._score_from_aqi(0) == 100.0
    assert air_quality._score_from_aqi(50) == 80.0
    assert air_quality._score_from_aqi(100) == 60.0
    assert air_quality._score_from_aqi(150) == 40.0
    assert air_quality._score_from_aqi(200) == 20.0
    assert air_quality._score_from_aqi(300) == 10.0
    assert air_quality._score_from_aqi(500) == 0.0


def test_category_labels():
    assert air_quality._category(10) == "Good"
    assert air_quality._category(500) == "Hazardous"


async def test_compute_ok(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"current": {"us_aqi": 45}})
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(air_quality, "get_client", lambda: mock_client)
    air_quality._cache._store.clear()

    result = await air_quality.compute(40.0, -73.0)

    assert result.status == FactorStatus.OK
    assert result.raw_value == 45
    assert result.score == pytest.approx(air_quality._score_from_aqi(45))


async def test_compute_upstream_failure_is_error_not_ok(monkeypatch):
    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(air_quality, "get_client", lambda: mock_client)
    air_quality._cache._store.clear()

    result = await air_quality.compute(1.0, 2.0)

    assert result.status == FactorStatus.ERROR
    assert result.score is None
