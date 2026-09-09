from __future__ import annotations

import pytest

from infra.geo import haversine_m, score_from_distance_decay


def test_haversine_same_point_is_zero():
    assert haversine_m(0, 0, 0, 0) == 0


def test_score_from_distance_decay():
    assert score_from_distance_decay(0, 500) == 100.0
    assert score_from_distance_decay(500, 500) == pytest.approx(36.79, abs=0.1)
