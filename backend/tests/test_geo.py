from __future__ import annotations

import pytest

from infra.geo import haversine_m, score_from_distance_decay, score_sweet_spot


def test_haversine_same_point_is_zero():
    assert haversine_m(0, 0, 0, 0) == 0


def test_score_from_distance_decay():
    assert score_from_distance_decay(0, 500) == 100.0
    assert score_from_distance_decay(500, 500) == pytest.approx(36.79, abs=0.1)


def test_score_sweet_spot_peaks_at_sweet_spot_not_at_zero():
    # Regression for the "right next to a nightclub" bug: distance 0 must NOT be the
    # best-scoring point for a sweet-spot factor.
    near = score_sweet_spot(0, sweet_spot_m=500, spread_far_m=500, spread_near_m=150)
    at_sweet_spot = score_sweet_spot(500, sweet_spot_m=500, spread_far_m=500, spread_near_m=150)
    assert at_sweet_spot > near
    assert at_sweet_spot == pytest.approx(100.0, abs=0.5)


def test_score_sweet_spot_far_settles_at_baseline_not_zero():
    far = score_sweet_spot(50_000, sweet_spot_m=500, spread_far_m=500, spread_near_m=150, baseline=40.0)
    assert far == pytest.approx(40.0, abs=0.5)


def test_score_sweet_spot_near_beats_far_when_penalty_is_mild():
    # Sanity check on the shape, not just the two anchor points: being adjacent should
    # still generally read as worse than the baseline for a strongly-penalized
    # category (nightlife-strength penalty).
    near = score_sweet_spot(0, sweet_spot_m=500, spread_far_m=500, spread_near_m=150, near_penalty_scale=1.0)
    assert near < 40.0


def test_score_sweet_spot_never_negative():
    assert score_sweet_spot(0, sweet_spot_m=100, spread_far_m=50, spread_near_m=500, near_penalty_scale=5.0) >= 0.0
