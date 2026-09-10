from __future__ import annotations

import dataclasses

from domain.models import UserProfile

from infra.geo import score_from_distance_decay, score_sweet_spot
from service.overpass_batch import ProximityCategory

# Primary radii are deliberately sized to where each scoring curve stops producing a
# meaningful number, not to a round guess. Measured against the curves below:
#   greenery @2500m -> 0.67/100      social hub @2000m -> 40.0 (== baseline)
#   healthcare @4000m -> 42.6 (baseline 40)
# Querying further than this in a dense city buys score differences below 1 point
# while multiplying the area Overpass has to scan - which is what was getting these
# requests rate-limited (429). The wider fallback_radius_m still covers sparse rural
# points, where the first query legitimately finds nothing.

# "Closer is always better" - no downside to proximity, only diminishing returns.
GREENERY = ProximityCategory(
    key="greenery_proximity",
    label="Greenery proximity",
    tags=[("leisure", "park"), ("landuse", "forest"), ("natural", "wood")],
    score_fn=lambda d: score_from_distance_decay(d, 500.0),
    primary_radius_m=2500,
    fallback_radius_m=8000,
)
WATER = ProximityCategory(
    key="water_proximity",
    label="Water proximity",
    tags=[("natural", "water"), ("waterway", "river"), ("waterway", "stream")],
    score_fn=lambda d: score_from_distance_decay(d, 800.0),
    primary_radius_m=3000,
    fallback_radius_m=8000,
)

# Sweet-spot categories - see infra.geo.score_sweet_spot for why these can't use the
# monotonic decay above: being immediately adjacent is a genuine downside for each of
# these, not a bonus.
HEALTHCARE = ProximityCategory(
    key="healthcare_proximity",
    label="Healthcare proximity",
    tags=[("amenity", "hospital"), ("amenity", "clinic")],
    score_fn=lambda d: score_sweet_spot(
        d, sweet_spot_m=1000.0, spread_far_m=1200.0, spread_near_m=300.0, near_penalty_scale=0.5
    ),
    primary_radius_m=4000,
    fallback_radius_m=15000,
    name_tag_keys=("name", "amenity"),
)
SOCIAL_HUB = ProximityCategory(
    key="social_hub_proximity",
    label="Social hub proximity",
    tags=[("amenity", "bar"), ("amenity", "nightclub"), ("amenity", "cafe"), ("shop", "mall")],
    score_fn=lambda d: score_sweet_spot(
        d, sweet_spot_m=500.0, spread_far_m=500.0, spread_near_m=150.0, near_penalty_scale=1.0
    ),
    primary_radius_m=2000,
    fallback_radius_m=8000,
    name_tag_keys=("name", "amenity", "shop"),
)
RELIGIOUS_SITE = ProximityCategory(
    key="religious_site_proximity",
    label="Religious site proximity",
    tags=[("amenity", "place_of_worship")],
    score_fn=lambda d: score_sweet_spot(
        d, sweet_spot_m=500.0, spread_far_m=500.0, spread_near_m=200.0, near_penalty_scale=0.7
    ),
    primary_radius_m=2000,
    fallback_radius_m=8000,
    name_tag_keys=("name", "religion", "denomination"),
)

# The set the aggregator batches together into as few Overpass calls as possible -
# see service/aggregator.py. Keep this in sync with FACTOR_REGISTRY's enabled keys.
ALL_CATEGORIES = [GREENERY, WATER, HEALTHCARE, SOCIAL_HUB, RELIGIOUS_SITE]


def for_profile(category: ProximityCategory, profile: UserProfile | None) -> ProximityCategory:
    """A copy of `category` narrowed to what this profile actually cares about.

    Only religious sites vary today. The filter deliberately requires a positive tag
    match, so the ~3% of places of worship with no `religion` tag are excluded rather
    than assumed to be the user's faith - guessing would be the false positive this
    app is built to avoid, and the honest cost is that a genuinely nearby temple with
    an incomplete OSM entry is missed.
    """
    if profile is None or profile.religion is None or category.key != RELIGIOUS_SITE.key:
        return category

    faith = profile.religion.value
    return dataclasses.replace(
        category,
        element_filter=lambda el: el.get("tags", {}).get("religion") == faith,
        subject=f"{faith} place of worship",
    )
