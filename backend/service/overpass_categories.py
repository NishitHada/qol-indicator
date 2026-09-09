from __future__ import annotations

from infra.geo import score_from_distance_decay, score_sweet_spot
from service.overpass_batch import ProximityCategory

# "Closer is always better" - no downside to proximity, only diminishing returns.
GREENERY = ProximityCategory(
    key="greenery_proximity",
    label="Greenery proximity",
    tags=[("leisure", "park"), ("landuse", "forest"), ("natural", "wood")],
    score_fn=lambda d: score_from_distance_decay(d, 500.0),
    primary_radius_m=3000,
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
    primary_radius_m=5000,
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
    primary_radius_m=3000,
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
    primary_radius_m=3000,
    fallback_radius_m=8000,
    name_tag_keys=("name", "religion", "denomination"),
)

# The set the aggregator batches together into as few Overpass calls as possible -
# see service/aggregator.py. Keep this in sync with FACTOR_REGISTRY's enabled keys.
ALL_CATEGORIES = [GREENERY, WATER, HEALTHCARE, SOCIAL_HUB, RELIGIOUS_SITE]
