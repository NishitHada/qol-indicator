from __future__ import annotations

import math


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_earth_m = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius_earth_m * math.asin(math.sqrt(a))


def score_from_distance_decay(distance_m: float, decay_m: float) -> float:
    return max(0.0, min(100.0, 100.0 * math.exp(-distance_m / decay_m)))


def score_sweet_spot(
    distance_m: float,
    sweet_spot_m: float,
    spread_far_m: float,
    spread_near_m: float,
    baseline: float = 40.0,
    peak: float = 100.0,
    near_penalty_scale: float = 1.0,
) -> float:
    """Inverted-U scoring for amenities that are bad right next to you (noise/nuisance),
    good at a walkable-but-not-adjacent distance, and merely mediocre once far away -
    e.g. nightlife, places of worship, hospitals. Unlike score_from_distance_decay
    (monotonic "closer is always better", correct for parks/water), this never lets
    "very close" outscore the sweet spot, and "far away" settles at `baseline` rather
    than decaying toward 0 - being far from a bar isn't nearly as bad as being right
    next to one, so it shouldn't be scored as though it were.

    - `sweet_spot_m` / `spread_far_m`: center and width of the reward bump.
    - `spread_near_m` / `near_penalty_scale`: width and strength of the near-zero
      penalty. A wider spread_near or higher near_penalty_scale makes proximity more
      punishing (e.g. nightlife should penalize harder than a hospital, whose noise
      footprint is milder).
    """
    far_bump = (peak - baseline) * math.exp(-((distance_m - sweet_spot_m) ** 2) / (2 * spread_far_m**2))
    near_penalty = near_penalty_scale * baseline * math.exp(-(distance_m**2) / (2 * spread_near_m**2))
    return max(0.0, min(100.0, baseline + far_bump - near_penalty))


def score_within_walk(distance_m: float, full_credit_m: float, decay_m: float, ceiling: float = 100.0) -> float:
    """Full marks anywhere inside a walkable radius, then exponential decay beyond it.

    Distinct from score_from_distance_decay, which starts falling from the very first
    metre: for an amenity you *walk to* (a bus stop, a pharmacy), 80m and 300m are the
    same lived experience, so scoring them 43 points apart would be false precision.
    `ceiling` caps what this can ever return, which is how a factor says "this
    evidence alone is not enough to certify the location as excellent" - see
    service/connectivity.py, where a lone bus stop is capped below a metro station.
    """
    if distance_m <= full_credit_m:
        return ceiling
    return max(0.0, min(ceiling, ceiling * math.exp(-(distance_m - full_credit_m) / decay_m)))
