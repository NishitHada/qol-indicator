from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from domain.models import FactorStatus
from service import local_osm, overpass_batch
from service.overpass_categories import GREENERY, WATER

# Central Bangalore (MG Road area) - inside the bundled extract.
BLR_LAT, BLR_LNG = 12.9716, 77.6046


def test_bundled_extract_is_present_and_covers_bangalore():
    assert local_osm.is_available(), "bundled extract missing - run scripts/build_bangalore_osm.py"
    assert local_osm.covers(BLR_LAT, BLR_LNG)


def test_bounds_exclude_places_outside_the_extract():
    assert not local_osm.covers(28.6139, 77.2090)  # Delhi
    assert not local_osm.covers(40.7829, -73.9654)  # New York


def test_elements_near_finds_real_bangalore_parks():
    parks = local_osm.elements_near(BLR_LAT, BLR_LNG, GREENERY.tags, 2500)
    assert parks, "expected parks near MG Road in the bundled extract"
    names = {e["tags"].get("name") for e in parks}
    assert any(n and "Park" in n for n in names)


def test_elements_near_respects_the_radius():
    tight = local_osm.elements_near(BLR_LAT, BLR_LNG, GREENERY.tags, 300)
    wide = local_osm.elements_near(BLR_LAT, BLR_LNG, GREENERY.tags, 3000)
    assert len(tight) < len(wide)


async def test_bangalore_resolves_with_zero_network_calls(monkeypatch):
    """The whole point of the bundled extract: inside its area, greenery/water resolve
    without touching Overpass at all - which is what made them permanently
    'couldn't verify' in production, since Overpass refuses cloud IPs."""
    client = MagicMock()
    client.post = AsyncMock(side_effect=AssertionError("must not hit the network inside the extract"))
    monkeypatch.setattr(overpass_batch, "get_client", lambda: client)
    overpass_batch._element_caches.clear()

    results = await overpass_batch.compute_categories(BLR_LAT, BLR_LNG, [GREENERY, WATER])

    assert client.post.call_count == 0
    assert results["greenery_proximity"].status == FactorStatus.OK
    assert results["water_proximity"].status == FactorStatus.OK
    assert results["greenery_proximity"].raw_value == pytest.approx(147, abs=60)
