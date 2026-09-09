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


async def test_multiple_categories_use_a_single_http_call(monkeypatch):
    cat_a = _cat("cat_a", ("amenity", "a_thing"))
    cat_b = _cat("cat_b", ("amenity", "b_thing"))
    elements = [
        {"type": "node", "lat": 1.001, "lon": 1.0, "tags": {"amenity": "a_thing"}},
        {"type": "node", "lat": 1.002, "lon": 1.0, "tags": {"amenity": "b_thing"}},
    ]
    client = _mock_client(elements)
    monkeypatch.setattr(overpass_batch, "get_client", lambda: client)
    overpass_batch._caches.clear()

    results = await overpass_batch.compute_categories(1.0, 1.0, [cat_a, cat_b])

    assert client.post.call_count == 1
    assert results["cat_a"].status == FactorStatus.OK
    assert results["cat_b"].status == FactorStatus.OK


async def test_elements_are_routed_to_the_matching_category_only(monkeypatch):
    cat_a = _cat("cat_a", ("amenity", "a_thing"))
    cat_b = _cat("cat_b", ("amenity", "b_thing"))
    # Only an a_thing element exists - b_thing should come back not_found, not
    # accidentally matched to the a_thing element.
    elements = [{"type": "node", "lat": 1.001, "lon": 1.0, "tags": {"amenity": "a_thing", "name": "A"}}]
    client = _mock_client(elements)
    monkeypatch.setattr(overpass_batch, "get_client", lambda: client)
    overpass_batch._caches.clear()

    results = await overpass_batch.compute_categories(1.0, 1.0, [cat_a, cat_b])

    assert results["cat_a"].status == FactorStatus.OK
    assert "A" in results["cat_a"].detail
    assert results["cat_b"].status == FactorStatus.NOT_FOUND


async def test_only_uncached_categories_are_fetched(monkeypatch):
    cat_a = _cat("cached_cat", ("amenity", "a_thing"))
    cat_b = _cat("uncached_cat", ("amenity", "b_thing"))
    overpass_batch._caches.clear()
    from domain.models import FactorResult

    cached_result = FactorResult(
        key="cached_cat", label="Cached Cat", score=99.0, raw_value=1.0, unit="meters", status=FactorStatus.OK
    )
    overpass_batch._cache_for(cat_a).set(overpass_batch.geo_cache_key(1.0, 1.0), cached_result)

    elements = [{"type": "node", "lat": 1.001, "lon": 1.0, "tags": {"amenity": "b_thing", "name": "B"}}]
    client = _mock_client(elements)
    monkeypatch.setattr(overpass_batch, "get_client", lambda: client)

    results = await overpass_batch.compute_categories(1.0, 1.0, [cat_a, cat_b])

    assert client.post.call_count == 1
    assert results["cached_cat"] == cached_result
    assert results["uncached_cat"].status == FactorStatus.OK
    # Only the uncached category's tag should appear in the query sent.
    sent_query = client.post.call_args.kwargs["data"]["data"]
    assert "b_thing" in sent_query
    assert "a_thing" not in sent_query


async def test_fallback_radius_only_retries_missing_categories(monkeypatch):
    cat_a = _cat("found_at_primary", ("amenity", "a_thing"))
    cat_b = _cat("needs_fallback", ("amenity", "b_thing"))

    call_queries = []

    async def fake_post(url, data):
        call_queries.append(data["data"])
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if len(call_queries) == 1:
            # Primary call: only cat_a's feature exists.
            elements = [{"type": "node", "lat": 1.001, "lon": 1.0, "tags": {"amenity": "a_thing", "name": "A"}}]
        else:
            # Fallback call: cat_b's feature only shows up at the wider radius.
            elements = [{"type": "node", "lat": 1.001, "lon": 1.0, "tags": {"amenity": "b_thing", "name": "B"}}]
        resp.json = MagicMock(return_value={"elements": elements})
        return resp

    client = MagicMock()
    client.post = AsyncMock(side_effect=fake_post)
    monkeypatch.setattr(overpass_batch, "get_client", lambda: client)
    overpass_batch._caches.clear()

    results = await overpass_batch.compute_categories(1.0, 1.0, [cat_a, cat_b])

    assert client.post.call_count == 2
    assert results["found_at_primary"].status == FactorStatus.OK
    assert results["needs_fallback"].status == FactorStatus.OK
    assert "B" in results["needs_fallback"].detail
    # The fallback call should only ask about the still-missing category.
    assert "b_thing" in call_queries[1]
    assert "a_thing" not in call_queries[1]


async def test_overpass_failure_errors_all_requested_categories(monkeypatch):
    cat_a = _cat("cat_a", ("amenity", "a_thing"))
    cat_b = _cat("cat_b", ("amenity", "b_thing"))
    client = MagicMock()
    client.post = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(overpass_batch, "get_client", lambda: client)
    overpass_batch._caches.clear()

    results = await overpass_batch.compute_categories(2.0, 2.0, [cat_a, cat_b])

    assert results["cat_a"].status == FactorStatus.ERROR
    assert results["cat_b"].status == FactorStatus.ERROR
