"""Personalization that changes what a factor *measures*, not just how much it counts.

The age rules are weight multipliers - they shift emphasis between factors but every
factor still measures the same thing. Religion and transport preference are different
in kind: they change the question being asked. These tests cover that distinction.
"""

from __future__ import annotations

import pytest

from domain.models import FactorStatus, Religion, TransportPreference, UserProfile
from service import aggregator, connectivity, osm_lookup, personalization
from service.overpass_categories import GREENERY, RELIGIOUS_SITE, for_profile

# A Bangalore point with several faiths' places of worship in range.
BLR_LAT, BLR_LNG = 12.9716, 77.6046


# --- Religion -------------------------------------------------------------------

def test_no_religion_leaves_the_category_untouched():
    assert for_profile(RELIGIOUS_SITE, None) is RELIGIOUS_SITE
    assert for_profile(RELIGIOUS_SITE, UserProfile(age=40)) is RELIGIOUS_SITE


def test_only_religious_sites_are_narrowed():
    """A profile must not quietly change what greenery or water means."""
    assert for_profile(GREENERY, UserProfile(religion=Religion.HINDU)) is GREENERY


def test_the_filter_matches_only_that_faith():
    category = for_profile(RELIGIOUS_SITE, UserProfile(religion=Religion.MUSLIM))
    assert category.element_filter({"tags": {"religion": "muslim"}})
    assert not category.element_filter({"tags": {"religion": "hindu"}})


def test_an_untagged_place_of_worship_is_excluded_not_assumed():
    """About 3% of Bangalore's places of worship carry no religion tag. Treating those
    as a match would be guessing in the user's favour, which is the false positive this
    app exists to avoid; the honest cost is missing a genuinely nearby site whose OSM
    entry is incomplete."""
    category = for_profile(RELIGIOUS_SITE, UserProfile(religion=Religion.HINDU))
    assert not category.element_filter({"tags": {"amenity": "place_of_worship"}})


def test_the_not_found_message_names_the_faith():
    category = for_profile(RELIGIOUS_SITE, UserProfile(religion=Religion.JAIN))
    assert category.described == "jain place of worship"
    assert RELIGIOUS_SITE.described == "religious site proximity"


async def test_a_faith_filter_changes_the_real_result():
    hindu = await aggregator.compute_all(BLR_LAT, BLR_LNG, UserProfile(religion=Religion.HINDU))
    muslim = await aggregator.compute_all(BLR_LAT, BLR_LNG, UserProfile(religion=Religion.MUSLIM))
    unfiltered = await aggregator.compute_all(BLR_LAT, BLR_LNG)

    key = RELIGIOUS_SITE.key
    assert hindu[key].detail != muslim[key].detail
    # The nearest site of a given faith can never be nearer than the nearest site of
    # any faith, so a filtered score can only ever be lower or equal.
    for filtered in (hindu[key], muslim[key]):
        if filtered.status == FactorStatus.OK:
            assert filtered.raw_value >= unfiltered[key].raw_value


# --- Transport preference -------------------------------------------------------

def _stub_transit(monkeypatch, elements):
    async def _nearby(lat, lng, tags, radius_m):
        return [el for el in elements if osm_lookup.matches(el, tags)]

    monkeypatch.setattr(connectivity.osm_lookup, "nearby", _nearby)
    connectivity._cache._store.clear()


METRO = {"lat": 12.9740, "lon": 77.6046, "tags": {"railway": "station", "station": "subway", "name": "Metro"}}
BUS = {"lat": BLR_LAT, "lon": BLR_LNG, "tags": {"highway": "bus_stop", "name": "Stop"}}


def test_no_preference_considers_every_mode():
    assert connectivity.modes_for(None) is connectivity.MODES
    assert connectivity.modes_for(UserProfile(age=30)) is connectivity.MODES


async def test_a_metro_preference_ignores_bus_stops(monkeypatch):
    _stub_transit(monkeypatch, [BUS])
    result = await connectivity.compute(BLR_LAT, BLR_LNG, UserProfile(transport_preference=TransportPreference.METRO))
    assert result.status == FactorStatus.OK
    assert result.score == 0.0
    assert "metro" in result.detail


async def test_a_bus_preference_ignores_metro_stations(monkeypatch):
    _stub_transit(monkeypatch, [METRO])
    result = await connectivity.compute(BLR_LAT, BLR_LNG, UserProfile(transport_preference=TransportPreference.BUS))
    assert result.score == 0.0
    assert "bus" in result.detail


async def test_without_a_preference_the_best_mode_still_wins(monkeypatch):
    _stub_transit(monkeypatch, [BUS, METRO])
    result = await connectivity.compute(BLR_LAT, BLR_LNG)
    assert result.score == 100.0


async def test_two_preferences_do_not_share_a_cached_answer(monkeypatch):
    """Same point, different question. This is the collision class that already bit
    the crowding factor once."""
    _stub_transit(monkeypatch, [BUS, METRO])
    metro = await connectivity.compute(BLR_LAT, BLR_LNG, UserProfile(transport_preference=TransportPreference.METRO))
    bus = await connectivity.compute(BLR_LAT, BLR_LNG, UserProfile(transport_preference=TransportPreference.BUS))
    assert metro.detail != bus.detail


# --- Cab: exclusion rather than narrowing ---------------------------------------

def test_a_cab_preference_excludes_connectivity():
    excluded = personalization.excluded_factors(UserProfile(transport_preference=TransportPreference.CAB))
    assert "connectivity" in excluded


def test_metro_and_bus_preferences_exclude_nothing():
    for preference in (TransportPreference.METRO, TransportPreference.BUS):
        assert personalization.excluded_factors(UserProfile(transport_preference=preference)) == {}


def test_an_excluded_factor_leaves_the_weights_entirely():
    base = {"connectivity": 0.2, "aqi": 0.8}
    weights, reasons = personalization.adjusted_weights(
        base, UserProfile(transport_preference=TransportPreference.CAB)
    )
    assert "connectivity" not in weights
    assert weights["aqi"] == pytest.approx(1.0)
    assert any("cab" in reason for reason in reasons)


async def test_an_excluded_factor_is_not_reported_as_unverified():
    """"You told us you do not use public transport" is not a gap in our data, and
    presenting it as one would make a personalized score look broken."""
    profile = UserProfile(transport_preference=TransportPreference.CAB)
    factors = await aggregator.compute_all(BLR_LAT, BLR_LNG, profile)
    overall = aggregator.compute_overall(factors, profile)

    assert "connectivity" in overall.excluded
    assert "connectivity" not in overall.unverified
    assert "connectivity" not in overall.weights_used
    assert sum(overall.weights_used.values()) == pytest.approx(1.0)


async def test_an_empty_profile_scores_exactly_like_no_profile():
    """Personalization stays opt-in: supplying a profile object with nothing set must
    not change a single weight."""
    factors = await aggregator.compute_all(BLR_LAT, BLR_LNG)
    plain = aggregator.compute_overall(factors, None)
    empty = aggregator.compute_overall(factors, UserProfile())
    assert plain.score == empty.score
    assert plain.weights_used == empty.weights_used
    assert empty.excluded == []
