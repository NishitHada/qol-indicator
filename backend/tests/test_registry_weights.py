from __future__ import annotations

from service.overpass_categories import ALL_CATEGORIES
from service.registry import FACTOR_REGISTRY


def test_enabled_weights_sum_to_one():
    """The aggregator does a straight weighted sum and deliberately does NOT
    renormalize away from a factor that failed, so the registry's weights have to
    balance on their own."""
    total = sum(d.weight for d in FACTOR_REGISTRY if d.enabled)
    assert round(total, 6) == 1.0


def test_disabled_factors_carry_no_weight():
    assert all(d.weight == 0.0 for d in FACTOR_REGISTRY if not d.enabled)


def test_factor_keys_are_unique():
    keys = [d.key for d in FACTOR_REGISTRY]
    assert len(keys) == len(set(keys))


def test_every_batched_category_is_an_enabled_factor():
    enabled = {d.key for d in FACTOR_REGISTRY if d.enabled}
    assert {c.key for c in ALL_CATEGORIES} <= enabled
