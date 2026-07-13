from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from domain.models import FactorStatus
from service import temperature


def test_comfort_base_within_band_is_perfect():
    assert temperature._comfort_base(18.0) == 100.0


def test_comfort_base_degrades_outside_band():
    assert temperature._comfort_base(30.0) < 100.0
    assert temperature._comfort_base(-5.0) < 100.0


async def test_compute_ok(monkeypatch):
    daily = {
        "temperature_2m_max": [30.0] * 360 + [40.0] * 5,
        "temperature_2m_min": [10.0] * 365,
        "temperature_2m_mean": [20.0] * 365,
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"daily": daily})
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(temperature, "get_client", lambda: mock_client)
    temperature._cache._store.clear()

    result = await temperature.compute(10.0, 20.0)

    assert result.status == FactorStatus.OK
    assert result.raw_value == 20.0
    assert "5 extreme days / 365" in result.detail


async def test_compute_upstream_failure_is_error_not_ok(monkeypatch):
    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(temperature, "get_client", lambda: mock_client)
    temperature._cache._store.clear()

    result = await temperature.compute(11.0, 21.0)

    assert result.status == FactorStatus.ERROR
    assert result.score is None
