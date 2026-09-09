from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from domain.models import FactorStatus
from service import local_climate, temperature

BLR_LAT, BLR_LNG = 12.9716, 77.6046


def test_bundled_climate_is_present_and_covers_bangalore():
    assert local_climate.is_available(), "bundled climate grid missing - run scripts/build_bangalore_climate.py"
    assert local_climate.covers(BLR_LAT, BLR_LNG)


def test_bounds_exclude_places_outside_the_grid():
    assert not local_climate.covers(28.6139, 77.2090)  # Delhi
    assert local_climate.daily_series(28.6139, 77.2090) is None


def test_daily_series_returns_a_full_year_of_three_aligned_series():
    series = local_climate.daily_series(BLR_LAT, BLR_LNG)
    assert series is not None
    highs, lows, means = series
    assert len(highs) == len(lows) == len(means)
    assert len(means) > 300  # a year's worth, allowing for archive lag
    assert all(isinstance(v, (int, float)) for v in means if v is not None)


async def test_bangalore_temperature_needs_no_network(monkeypatch):
    """Open-Meteo's archive 429s from Render's shared IP, which is why this factor
    was permanently failing in production - inside the bundled grid it must not make
    a request at all."""
    client = MagicMock()
    client.get = AsyncMock(side_effect=AssertionError("must not hit the network inside the bundled grid"))
    monkeypatch.setattr(temperature, "get_client", lambda: client)
    temperature._cache._store.clear()

    result = await temperature.compute(BLR_LAT, BLR_LNG)

    assert client.get.call_count == 0
    assert result.status == FactorStatus.OK
    assert result.score is not None
    # Bangalore's annual mean sits in the low-to-mid 20s.
    assert 18.0 < result.raw_value < 30.0
