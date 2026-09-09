from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from domain.models import FactorStatus
from service import local_climate, wind_ventilation

BLR_LAT, BLR_LNG = 12.9716, 77.6046


def test_direction_variety_rewards_a_year_that_changes_direction():
    """The half of ventilation that mean wind speed cannot express: a flat only gets
    cross-ventilation if the wind sometimes arrives from the other side."""
    one_way = wind_ventilation._direction_variety([270.0] * 365)
    all_ways = wind_ventilation._direction_variety([i * 45.0 % 360 for i in range(368)])
    assert one_way == 0.0
    assert all_ways == 100.0  # 368 days spread evenly over the 8 sectors
    assert 0 < wind_ventilation._direction_variety([270.0] * 300 + [90.0] * 65) < 100


def test_direction_variety_of_no_data_is_zero_not_a_crash():
    assert wind_ventilation._direction_variety([]) == 0.0
    assert wind_ventilation._direction_variety([None, None]) == 0.0


def test_speed_above_the_good_threshold_does_not_keep_climbing():
    assert wind_ventilation._speed_component(wind_ventilation.GOOD_WIND_KMH) == 100.0
    assert wind_ventilation._speed_component(60.0) == 100.0
    assert wind_ventilation._speed_component(0.0) == 0.0


def test_bundled_climate_carries_wind():
    assert local_climate.wind_series(BLR_LAT, BLR_LNG) is not None, (
        "climate bundle predates the wind fields - re-run scripts/build_bangalore_climate.py"
    )


async def test_bangalore_needs_no_network(monkeypatch):
    client = MagicMock()
    client.get = AsyncMock(side_effect=AssertionError("must not hit the network inside the bundled grid"))
    monkeypatch.setattr(wind_ventilation, "get_client", lambda: client)
    wind_ventilation._cache._store.clear()

    result = await wind_ventilation.compute(BLR_LAT, BLR_LNG)

    assert client.get.call_count == 0
    assert result.status == FactorStatus.OK
    assert result.score is not None
    assert 0 < result.raw_value < 60


async def test_outside_the_grid_falls_back_to_the_archive(monkeypatch):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(
        return_value={"daily": {"wind_speed_10m_max": [20.0] * 10, "wind_direction_10m_dominant": [90.0] * 10}}
    )
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    monkeypatch.setattr(wind_ventilation, "get_client", lambda: client)
    wind_ventilation._cache._store.clear()

    result = await wind_ventilation.compute(51.5074, -0.1278)  # London

    assert client.get.call_count == 1
    assert result.status == FactorStatus.OK
    # Strong but single-direction wind: full speed marks, no variety marks.
    assert result.score == round(100.0 * wind_ventilation.SPEED_WEIGHT, 1)


async def test_archive_failure_outside_the_grid_is_an_error(monkeypatch):
    client = MagicMock()
    client.get = AsyncMock(side_effect=RuntimeError("429"))
    monkeypatch.setattr(wind_ventilation, "get_client", lambda: client)
    wind_ventilation._cache._store.clear()

    result = await wind_ventilation.compute(51.5074, -0.1278)

    assert result.status == FactorStatus.ERROR
    assert result.score is None
