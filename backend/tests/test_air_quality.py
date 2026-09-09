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


def test_daily_means_groups_by_calendar_day():
    times = ["2025-01-01T00:00", "2025-01-01T12:00", "2025-01-02T00:00"]
    values = [10.0, 20.0, 100.0]
    means = air_quality._daily_means(times, values)
    assert sorted(means) == [15.0, 100.0]


def test_daily_means_skips_null_hours():
    times = ["2025-01-01T00:00", "2025-01-01T12:00"]
    values = [10.0, None]
    means = air_quality._daily_means(times, values)
    assert means == [10.0]


def _mock_hourly_response(daily_values: dict[str, list[float]]):
    times = []
    values = []
    for day, hours in daily_values.items():
        for i, v in enumerate(hours):
            times.append(f"{day}T{i:02d}:00")
            values.append(v)
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"hourly": {"time": times, "us_aqi": values}})
    return resp


async def test_compute_ok_uses_yearly_average_not_a_snapshot(monkeypatch):
    # 3 good days, 1 bad day - average should reflect the whole window, not any
    # single day, and the bad day should show up in the bad-day count.
    resp = _mock_hourly_response(
        {
            "2025-01-01": [40, 40],
            "2025-01-02": [40, 40],
            "2025-01-03": [40, 40],
            "2025-01-04": [150, 150],
        }
    )
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=resp)
    monkeypatch.setattr(air_quality, "get_client", lambda: mock_client)
    air_quality._cache._store.clear()

    result = await air_quality.compute(40.0, -73.0)

    assert result.status == FactorStatus.OK
    assert result.raw_value == pytest.approx(67.5)  # mean of [40,40,40,150]
    assert "1 bad-air days / 4" in result.detail


async def test_compute_penalizes_frequent_bad_days_beyond_the_average(monkeypatch):
    # Same average AQI (100) achieved two ways: consistently moderate vs. half the
    # days spiking badly - the spiky one must score worse.
    consistent = _mock_hourly_response({f"2025-01-{d:02d}": [100] for d in range(1, 5)})
    spiky = _mock_hourly_response(
        {
            "2025-01-01": [50],
            "2025-01-02": [50],
            "2025-01-03": [150],
            "2025-01-04": [150],
        }
    )
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=consistent)
    monkeypatch.setattr(air_quality, "get_client", lambda: mock_client)
    air_quality._cache._store.clear()
    consistent_result = await air_quality.compute(1.0, 1.0)

    mock_client.get = AsyncMock(return_value=spiky)
    air_quality._cache._store.clear()
    spiky_result = await air_quality.compute(2.0, 2.0)

    assert spiky_result.raw_value == pytest.approx(consistent_result.raw_value)
    assert spiky_result.score < consistent_result.score


async def test_compute_upstream_failure_is_error_not_ok(monkeypatch):
    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(air_quality, "get_client", lambda: mock_client)
    air_quality._cache._store.clear()

    result = await air_quality.compute(1.0, 2.0)

    assert result.status == FactorStatus.ERROR
    assert result.score is None
