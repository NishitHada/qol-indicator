from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from domain.models import FactorStatus
from service import healthcare_proximity, religious_site_proximity, social_hub_proximity


def _mock_client(elements):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"elements": elements})
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    return client


@pytest.mark.parametrize(
    "module,tag,name,expected_key",
    [
        (social_hub_proximity, ("amenity", "bar"), "Test Bar", "social_hub_proximity"),
        (healthcare_proximity, ("amenity", "hospital"), "Test Hospital", "healthcare_proximity"),
        (religious_site_proximity, ("amenity", "place_of_worship"), "Test Temple", "religious_site_proximity"),
    ],
)
async def test_compute_found_and_cached(monkeypatch, module, tag, name, expected_key):
    k, v = tag
    elements = [{"type": "node", "lat": 10.001, "lon": 20.0, "tags": {k: v, "name": name}}]
    client = _mock_client(elements)
    monkeypatch.setattr("service.overpass_proximity.get_client", lambda: client)
    module._cache._store.clear()

    result = await module.compute(10.0, 20.0)

    assert result.status == FactorStatus.OK
    assert result.key == expected_key
    assert name in result.detail

    # Second call should hit the module's own cache, not the network again.
    call_count_before = client.post.call_count
    cached_result = await module.compute(10.0, 20.0)
    assert client.post.call_count == call_count_before
    assert cached_result == result
