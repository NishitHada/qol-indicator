from __future__ import annotations

import pytest

from domain.models import (
    UNVERIFIED_FLOOR_SCORE,
    FactorDefinition,
    FactorResult,
    FactorStatus,
    VendorAdapter,
)
from service import aggregator


async def _ok_vendor_low(lat, lng):
    return FactorResult(key="a", label="A", score=90.0, raw_value=1, unit="u", status=FactorStatus.OK)


async def _failing_vendor(lat, lng):
    raise RuntimeError("vendor down")


async def _ok_vendor_second(lat, lng):
    return FactorResult(key="a", label="A", score=70.0, raw_value=1, unit="u", status=FactorStatus.OK)


def test_compute_overall_all_ok_is_plain_weighted_average(monkeypatch):
    defs = [
        FactorDefinition("a", "A", 0.5, True, vendors=[]),
        FactorDefinition("b", "B", 0.5, True, vendors=[]),
    ]
    monkeypatch.setattr(aggregator, "FACTOR_REGISTRY", defs)
    results = {
        "a": FactorResult(key="a", label="A", score=90.0, raw_value=1, unit="u", status=FactorStatus.OK),
        "b": FactorResult(key="b", label="B", score=80.0, raw_value=1, unit="u", status=FactorStatus.OK),
    }

    overall, weights, unverified = aggregator.compute_overall(results)

    assert overall == pytest.approx(85.0)
    assert unverified == []


def test_error_factor_pulls_score_down_instead_of_being_excluded(monkeypatch):
    defs = [
        FactorDefinition("a", "A", 0.5, True, vendors=[]),
        FactorDefinition("b", "B", 0.5, True, vendors=[]),
    ]
    monkeypatch.setattr(aggregator, "FACTOR_REGISTRY", defs)
    results = {
        "a": FactorResult(key="a", label="A", score=90.0, raw_value=1, unit="u", status=FactorStatus.OK),
        "b": FactorResult(key="b", label="B", score=None, raw_value=None, unit=None, status=FactorStatus.ERROR),
    }

    overall, weights, unverified = aggregator.compute_overall(results)

    # If b's weight were renormalized away, overall would be 90.0 (just "a").
    # The no-false-positives rule requires b to contribute the conservative floor instead.
    naive_renormalized_score = 90.0
    expected = 0.5 * 90.0 + 0.5 * UNVERIFIED_FLOOR_SCORE
    assert overall == pytest.approx(expected)
    assert overall < naive_renormalized_score
    assert unverified == ["b"]


def test_not_found_factor_also_uses_conservative_floor(monkeypatch):
    defs = [FactorDefinition("a", "A", 1.0, True, vendors=[])]
    monkeypatch.setattr(aggregator, "FACTOR_REGISTRY", defs)
    results = {
        "a": FactorResult(key="a", label="A", score=None, raw_value=None, unit=None, status=FactorStatus.NOT_FOUND),
    }

    overall, weights, unverified = aggregator.compute_overall(results)

    assert overall == pytest.approx(UNVERIFIED_FLOOR_SCORE)
    assert unverified == ["a"]


async def test_compute_all_falls_back_across_vendors(monkeypatch):
    defs = [
        FactorDefinition(
            "a",
            "A",
            1.0,
            True,
            vendors=[VendorAdapter("v1-down", _failing_vendor), VendorAdapter("v2-up", _ok_vendor_second)],
        ),
    ]
    monkeypatch.setattr(aggregator, "FACTOR_REGISTRY", defs)

    results = await aggregator.compute_all(1.0, 1.0)

    assert results["a"].status == FactorStatus.OK
    assert results["a"].source == "v2-up"
    assert results["a"].score == 70.0
