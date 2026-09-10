"""Ground-truth regression fixtures for known Bangalore locations.

The rest of the suite checks that each factor computes what its own code says it
should. This file checks something different and harder: that the numbers coming out
match what a person who knows the city would say about these places. A scoring curve
can be internally consistent, fully covered by unit tests, and still rank Chickpet
above Sadashivanagar for open space.

**The expectations here are judgment, not measurement.** They are one person's read of
these neighbourhoods, and the coordinates are approximate points within them, not
official boundaries. So a failure here means "go and look", not automatically "the code
is wrong" - the expectation may be the thing that is wrong, or the point may have
drifted to the wrong side of a road. What a failure does reliably tell you is that the
behaviour changed, which is the whole point of a fixture set.

Assertions are deliberately weighted toward *relative* orderings rather than absolute
values. "Dollars Colony is less crowded than Chickpet" survives a threshold tweak and a
data refresh; "Chickpet scores 0" does not. Where an absolute band is asserted, it is
wide enough to absorb an OSM or footprint refresh.

Adding a location means adding a row to PLACES and whatever rows in ORDERINGS and
BANDS you can defend. Both tables are declarative, in the same spirit as
FACTOR_REGISTRY.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from domain.models import FactorStatus
from service import (
    aggregator,
    air_quality,
    connectivity,
    crowding,
    daily_essentials,
    noise_sources,
    pollution_sources,
    temperature,
    wind_ventilation,
)


@dataclass(frozen=True)
class Place:
    lat: float
    lng: float
    character: str


PLACES: dict[str, Place] = {
    "cubbon_park": Place(12.9763, 77.5929, "large central park"),
    "lalbagh": Place(12.9507, 77.5848, "large park with a lake"),
    "mg_road": Place(12.9756, 77.6068, "central commercial spine, on the metro"),
    "indiranagar": Place(12.9784, 77.6408, "upmarket residential, on the metro, on a major road"),
    "koramangala": Place(12.9352, 77.6245, "upmarket residential, no metro"),
    "whitefield": Place(12.9856, 77.7368, "tech corridor, on the metro"),
    "airport": Place(13.1986, 77.7066, "Kempegowda International Airport"),
    "peenya": Place(13.0290, 77.5190, "large industrial estate"),
    "chickpet": Place(12.9690, 77.5760, "dense historic commercial core"),
    "shivajinagar": Place(12.9850, 77.6050, "dense inner-city area"),
    "dollars_colony": Place(13.0230, 77.5760, "low-density bungalow layout"),
    "sadashivanagar": Place(13.0072, 77.5800, "affluent leafy residential"),
    "bellandur": Place(12.9260, 77.6680, "lake known for sewage inflow"),
    "hebbal_lake": Place(13.0450, 77.5910, "large lake with parkland"),
    "jayanagar": Place(12.9250, 77.5830, "established planned residential, on the metro"),
    "rural_edge": Place(13.2400, 77.3400, "farmland at the north-west edge of the bounds"),
}

# Everywhere a person could actually live or work. rural_edge is excluded because
# "nothing here" is the correct answer for several factors there.
URBAN = [k for k in PLACES if k != "rural_edge"]

# (better_place, worse_place, factor, why) - asserted as a strict inequality.
ORDERINGS = [
    ("cubbon_park", "mg_road", "greenery_proximity", "a park beats the commercial street beside it"),
    ("hebbal_lake", "rural_edge", "greenery_proximity", "parkland beats farmland with no mapped green space"),
    ("hebbal_lake", "mg_road", "water_proximity", "a lake beats an inland commercial street"),
    ("dollars_colony", "chickpet", "crowding", "a bungalow layout has more open space than a historic core"),
    ("dollars_colony", "shivajinagar", "crowding", "same, against the other dense inner-city fixture"),
    ("sadashivanagar", "chickpet", "crowding", "affluent low-rise beats a historic core"),
    ("mg_road", "rural_edge", "daily_essentials", "the city centre beats farmland for errands"),
    ("indiranagar", "rural_edge", "connectivity", "a metro station beats a distant railway halt"),
    ("jayanagar", "peenya", "pollution_sources", "planned residential beats a large industrial estate"),
    ("cubbon_park", "bellandur", "bad_odour", "a park beats a lake with sewage inflow"),
    ("dollars_colony", "airport", "noise_sources", "an interior residential street beats an airport"),
]

# (place, factor, low, high, why) - inclusive band, deliberately wide.
BANDS = [
    ("chickpet", "crowding", 0.0, 25.0, "one of the most tightly built areas in the city"),
    ("shivajinagar", "crowding", 0.0, 25.0, "dense inner city, very little open ground"),
    ("dollars_colony", "crowding", 75.0, 100.0, "large plots, generous setbacks"),
    ("cubbon_park", "greenery_proximity", 80.0, 100.0, "inside a major park"),
    ("hebbal_lake", "greenery_proximity", 80.0, 100.0, "inside lakeside parkland"),
    ("airport", "noise_sources", 0.0, 40.0, "an international airport is the loudest thing we model"),
    ("indiranagar", "noise_sources", 0.0, 30.0, "the fixture point sits on 100 Feet Road"),
    ("rural_edge", "daily_essentials", 0.0, 20.0, "no shops, pharmacy, school or bank for kilometres"),
    ("rural_edge", "connectivity", 0.0, 35.0, "no metro, no bus stop, only a distant railway halt"),
    ("peenya", "pollution_sources", 0.0, 40.0, "inside a large industrial estate"),
    (
        "dollars_colony",
        "connectivity",
        0.0,
        75.0,
        "well-off but bus-only: without a metro station it must not score like one",
    ),
    (
        "cubbon_park",
        "pollution_sources",
        55.0,
        100.0,
        "the park's own small sewage plant must not be penalised like a municipal one",
    ),
]

# Places on the Namma Metro network, where connectivity should be maxed out.
ON_THE_METRO = ["mg_road", "indiranagar", "chickpet", "jayanagar", "whitefield"]


# Air quality is the one factor with no bundled data, so it is the one that can be
# unverified in an offline or rate-limited test run. Everything else must resolve from
# the bundles, and that is what these fixtures are here to guarantee.
LIVE_FACTORS = {"aqi"}

_MEMO: dict[str, dict] = {}


async def _factors(key: str) -> dict:
    """Scores a place once per session, with the street-scale caches cleared first.

    Clearing matters: these fixtures sit close enough together that a stale entry could
    quietly answer for the neighbouring place, which is the bug this file was written
    to catch. Memoising matters too - the bundled reads are deterministic, so scoring
    the same place for every assertion would only re-hit the one live upstream.
    """
    if key not in _MEMO:
        for module in (connectivity, crowding, daily_essentials, noise_sources, pollution_sources):
            module._cache._store.clear()
        place = PLACES[key]
        _MEMO[key] = await aggregator.compute_all(place.lat, place.lng)
    return _MEMO[key]


@pytest.mark.parametrize(("better", "worse", "factor", "why"), ORDERINGS)
async def test_relative_ordering(better: str, worse: str, factor: str, why: str):
    b = (await _factors(better))[factor]
    w = (await _factors(worse))[factor]
    assert b.score is not None and w.score is not None, f"{factor} did not resolve for both places"
    assert b.score > w.score, (
        f"{better} ({b.score}, {b.detail}) should beat {worse} ({w.score}, {w.detail}) "
        f"on {factor}: {why}"
    )


@pytest.mark.parametrize(("place", "factor", "low", "high", "why"), BANDS)
async def test_absolute_band(place: str, factor: str, low: float, high: float, why: str):
    result = (await _factors(place))[factor]
    assert result.score is not None, f"{factor} did not resolve for {place}"
    assert low <= result.score <= high, (
        f"{place} scored {result.score} on {factor}, expected {low}-{high} "
        f"({result.detail}): {why}"
    )


@pytest.mark.parametrize("place", ON_THE_METRO)
async def test_metro_served_places_max_out_connectivity(place: str):
    result = (await _factors(place))["connectivity"]
    assert result.score == 100.0, f"{place} is on the metro but scored {result.score}: {result.detail}"


@pytest.mark.parametrize("place", URBAN)
async def test_every_factor_resolves_for_a_real_address(place: str):
    """The bundled datasets exist so that a real Bangalore address resolves without a
    network call. Anything unverified here other than live air quality is a regression
    in the bundle, not a property of the location."""
    factors = await _factors(place)
    _, weights, unverified, _ = aggregator.compute_overall(factors)
    assert set(unverified) <= LIVE_FACTORS, f"{place} left {unverified} unverified"
    assert len(weights) == 14


@pytest.mark.parametrize("place", list(PLACES))
async def test_scores_stay_inside_the_scale(place: str):
    for key, result in (await _factors(place)).items():
        if result.score is None:
            continue
        assert 0.0 <= result.score <= 100.0, f"{place}/{key} scored {result.score}"


async def test_nearby_but_distinct_places_do_not_share_a_cached_answer():
    """Regression: at the old ~1.1km cache precision, MG Road and Shivajinagar hashed
    to the same bucket, so whichever was scored first answered for both. Shivajinagar's
    crowding came back as 83 when its real value is 0.

    This deliberately does not go through _factors: that clears the caches between
    places, which is exactly what stops the collision from happening. Two nearby points
    scored back to back through one warm cache is what production does.
    """
    crowding._cache._store.clear()
    mg_road = PLACES["mg_road"]
    shivajinagar = PLACES["shivajinagar"]

    first = await crowding.compute(mg_road.lat, mg_road.lng)
    second = await crowding.compute(shivajinagar.lat, shivajinagar.lng)

    assert first.score != second.score, (
        "two distinct localities returned an identical crowding score - the cache key "
        "is coarser than what this factor resolves"
    )
    assert first.detail != second.detail


async def test_the_city_centre_outranks_the_rural_edge_overall():
    """The composite is the product, so it gets an end-to-end assertion of its own."""
    centre, _, _, _ = aggregator.compute_overall(await _factors("mg_road"))
    edge, _, _, _ = aggregator.compute_overall(await _factors("rural_edge"))
    assert centre > edge
