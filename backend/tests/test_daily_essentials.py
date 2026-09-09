from __future__ import annotations

from domain.models import FactorStatus
from service import daily_essentials, osm_lookup

LAT, LNG = 12.9716, 77.6046


def _patch(monkeypatch, elements):
    async def _nearby(lat, lng, tags, radius_m):
        return [el for el in elements if osm_lookup.matches(el, tags)]

    monkeypatch.setattr(daily_essentials.osm_lookup, "nearby", _nearby)
    daily_essentials._cache._store.clear()


def _at(lat, lng, tags):
    return {"lat": lat, "lon": lng, "tags": tags}


async def test_all_four_errands_on_the_doorstep_scores_full(monkeypatch):
    _patch(
        monkeypatch,
        [
            _at(LAT, LNG, {"shop": "supermarket"}),
            _at(LAT, LNG, {"amenity": "pharmacy"}),
            _at(LAT, LNG, {"amenity": "school"}),
            _at(LAT, LNG, {"amenity": "bank"}),
        ],
    )
    result = await daily_essentials.compute(LAT, LNG)
    assert result.status == FactorStatus.OK
    assert result.score == 100.0
    assert result.raw_value == 4


async def test_one_category_cannot_carry_the_score(monkeypatch):
    """Twenty supermarkets and nothing else is not a well-served location. Averaging
    only over the categories that were found would score this 100 - exactly the false
    positive the scoring philosophy forbids."""
    _patch(monkeypatch, [_at(LAT, LNG, {"shop": "supermarket"}) for _ in range(20)])
    result = await daily_essentials.compute(LAT, LNG)
    assert result.score == 25.0
    assert "no pharmacy/school/banking" in result.detail


async def test_missing_categories_are_named_in_the_detail(monkeypatch):
    _patch(monkeypatch, [_at(LAT, LNG, {"amenity": "school"}), _at(LAT, LNG, {"amenity": "atm"})])
    result = await daily_essentials.compute(LAT, LNG)
    assert result.raw_value == 2
    assert "groceries" in result.detail and "pharmacy" in result.detail


async def test_walkable_distances_are_not_split_hairs_over(monkeypatch):
    """80m and 300m to a supermarket are the same errand, so they must score the same -
    a plain distance decay would put 30 points between them."""
    near = [_at(LAT + 0.0007, LNG, {"shop": "supermarket"})]  # ~78m
    _patch(monkeypatch, near)
    a = await daily_essentials.compute(LAT, LNG)
    _patch(monkeypatch, [_at(LAT + 0.0027, LNG, {"shop": "supermarket"})])  # ~300m
    b = await daily_essentials.compute(LAT, LNG)
    assert a.score == b.score


async def test_lookup_failure_is_an_error(monkeypatch):
    async def _boom(lat, lng, tags, radius_m):
        raise RuntimeError("down")

    monkeypatch.setattr(daily_essentials.osm_lookup, "nearby", _boom)
    daily_essentials._cache._store.clear()
    result = await daily_essentials.compute(LAT, LNG)
    assert result.status == FactorStatus.ERROR
    assert result.score is None


async def test_real_bangalore_point_resolves_from_the_bundle():
    daily_essentials._cache._store.clear()
    result = await daily_essentials.compute(12.9352, 77.6245)  # Koramangala
    assert result.status == FactorStatus.OK
    assert result.raw_value == len(daily_essentials.GROUPS)
