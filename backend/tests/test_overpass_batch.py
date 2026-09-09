from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from domain.models import FactorStatus
from service import overpass_batch
from service.overpass_batch import ProximityCategory


def _cat(key, tag, radius=1000, fallback=5000, score_fn=lambda d: 100.0 - d):
    k, v = tag
    return ProximityCategory(
        key=key,
        label=key.replace("_", " ").title(),
        tags=[(k, v)],
        score_fn=score_fn,
        primary_radius_m=radius,
        fallback_radius_m=fallback,
    )


def _mock_client(elements):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"elements": elements})
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    return client


async def test_categories_are_fetched_one_request_each_and_spread_across_mirrors(monkeypatch):
    """One request per category, issued concurrently and starting on different
    mirrors. A single combined multi-category query was tried first and got 429'd for
    being too heavy in a dense city - see compute_categories' docstring."""
    cat_a = _cat("cat_a", ("amenity", "a_thing"))
    cat_b = _cat("cat_b", ("amenity", "b_thing"))
    elements = [
        {"type": "node", "lat": 1.001, "lon": 1.0, "tags": {"amenity": "a_thing"}},
        {"type": "node", "lat": 1.002, "lon": 1.0, "tags": {"amenity": "b_thing"}},
    ]
    client = _mock_client(elements)
    monkeypatch.setattr(overpass_batch, "get_client", lambda: client)
    overpass_batch._element_caches.clear()

    results = await overpass_batch.compute_categories(1.0, 1.0, [cat_a, cat_b])

    assert client.post.call_count == 2  # one per category, not one per category per mirror
    urls = [c.args[0] for c in client.post.call_args_list]
    assert urls[0] != urls[1]  # spread across the cluster rather than stacking on one
    assert results["cat_a"].status == FactorStatus.OK
    assert results["cat_b"].status == FactorStatus.OK


async def test_elements_are_routed_to_the_matching_category_only(monkeypatch):
    cat_a = _cat("cat_a", ("amenity", "a_thing"))
    cat_b = _cat("cat_b", ("amenity", "b_thing"))
    elements = [{"type": "node", "lat": 1.001, "lon": 1.0, "tags": {"amenity": "a_thing", "name": "A"}}]
    client = _mock_client(elements)
    monkeypatch.setattr(overpass_batch, "get_client", lambda: client)
    overpass_batch._element_caches.clear()

    results = await overpass_batch.compute_categories(1.0, 1.0, [cat_a, cat_b])

    assert results["cat_a"].status == FactorStatus.OK
    assert "A" in results["cat_a"].detail
    # cat_b found nothing in the tile and nothing in its fallback query either.
    assert results["cat_b"].status == FactorStatus.NOT_FOUND


async def test_nearby_points_in_the_same_tile_reuse_one_fetch(monkeypatch):
    """The core fix for 'why is greenery unverified when I can see a park' - panning
    around a neighbourhood must not issue a request per click."""
    cat = _cat("parks", ("leisure", "park"))
    elements = [{"type": "node", "lat": 1.004, "lon": 1.004, "tags": {"leisure": "park", "name": "Tile Park"}}]
    client = _mock_client(elements)
    monkeypatch.setattr(overpass_batch, "get_client", lambda: client)
    overpass_batch._element_caches.clear()

    first = await overpass_batch.compute_categories(1.001, 1.001, [cat])
    calls_after_first = client.post.call_count
    # A different point a couple of hundred metres away, unambiguously in the same
    # cell (both floor to 1.000, 1.000) - chosen explicitly rather than relying on
    # where floating-point rounding happens to land.
    second = await overpass_batch.compute_categories(1.003, 1.003, [cat])
    assert overpass_batch.tile_key(1.001, 1.001) == overpass_batch.tile_key(1.003, 1.003)

    assert first["parks"].status == FactorStatus.OK
    assert second["parks"].status == FactorStatus.OK
    assert client.post.call_count == calls_after_first  # no new network call
    # Distances differ because they're genuinely different points, computed locally.
    assert first["parks"].raw_value != second["parks"].raw_value


async def test_failover_moves_to_the_next_mirror(monkeypatch):
    cat = _cat("parks", ("leisure", "park"))
    good_resp = MagicMock()
    good_resp.raise_for_status = MagicMock()
    good_resp.json = MagicMock(
        return_value={"elements": [{"type": "node", "lat": 1.001, "lon": 1.0, "tags": {"leisure": "park"}}]}
    )
    calls: list[str] = []

    async def flaky_post(url, data, timeout=None):
        calls.append(url)
        if len(calls) == 1:
            raise RuntimeError("first mirror down")
        return good_resp

    client = MagicMock()
    client.post = AsyncMock(side_effect=flaky_post)
    monkeypatch.setattr(overpass_batch, "get_client", lambda: client)
    overpass_batch._element_caches.clear()

    results = await overpass_batch.compute_categories(1.0, 1.0, [cat])

    assert results["parks"].status == FactorStatus.OK
    assert len(calls) == 2
    assert calls[0] != calls[1]  # actually moved to a different mirror


async def test_all_mirrors_failing_errors_the_categories(monkeypatch):
    cat_a = _cat("cat_a", ("amenity", "a_thing"))
    cat_b = _cat("cat_b", ("amenity", "b_thing"))
    client = MagicMock()
    client.post = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(overpass_batch, "get_client", lambda: client)
    overpass_batch._element_caches.clear()

    results = await overpass_batch.compute_categories(2.0, 2.0, [cat_a, cat_b])

    assert results["cat_a"].status == FactorStatus.ERROR
    assert results["cat_b"].status == FactorStatus.ERROR
    # Each category tried every mirror before giving up.
    assert client.post.call_count == 2 * len(overpass_batch.OVERPASS_MIRRORS)


async def test_tile_key_groups_nearby_points_and_separates_distant_ones():
    # Both inside the same ~550m cell (floor to 12.970, 77.600).
    assert overpass_batch.tile_key(12.9716, 77.6046) == overpass_batch.tile_key(12.9740, 77.6030)
    assert overpass_batch.tile_key(12.9716, 77.6046) != overpass_batch.tile_key(13.5000, 77.6046)
