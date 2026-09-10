from __future__ import annotations

import pytest

from domain.models import (
    UNVERIFIED_FLOOR_SCORE,
    FactorDefinition,
    FactorResult,
    FactorStatus,
    UserProfile,
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

    result = aggregator.compute_overall(results)

    assert result.score == pytest.approx(85.0)
    assert result.unverified == []
    assert result.personalization_applied == []


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

    result = aggregator.compute_overall(results)

    # If b's weight were renormalized away, overall would be 90.0 (just "a").
    # The no-false-positives rule requires b to contribute the conservative floor instead.
    naive_renormalized_score = 90.0
    expected = 0.5 * 90.0 + 0.5 * UNVERIFIED_FLOOR_SCORE
    assert result.score == pytest.approx(expected)
    assert result.score < naive_renormalized_score
    assert result.unverified == ["b"]
    assert result.personalization_applied == []


def test_not_found_factor_also_uses_conservative_floor(monkeypatch):
    defs = [FactorDefinition("a", "A", 1.0, True, vendors=[])]
    monkeypatch.setattr(aggregator, "FACTOR_REGISTRY", defs)
    results = {
        "a": FactorResult(key="a", label="A", score=None, raw_value=None, unit=None, status=FactorStatus.NOT_FOUND),
    }

    result = aggregator.compute_overall(results)

    assert result.score == pytest.approx(UNVERIFIED_FLOOR_SCORE)
    assert result.unverified == ["a"]
    assert result.personalization_applied == []


def test_personalization_boosts_matching_factor_and_renormalizes(monkeypatch):
    defs = [
        FactorDefinition("social_hub_proximity", "Social hub", 0.5, True, vendors=[]),
        FactorDefinition("aqi", "Air quality", 0.5, True, vendors=[]),
    ]
    monkeypatch.setattr(aggregator, "FACTOR_REGISTRY", defs)
    results = {
        "social_hub_proximity": FactorResult(
            key="social_hub_proximity", label="Social hub", score=80.0, raw_value=1, unit="u", status=FactorStatus.OK
        ),
        "aqi": FactorResult(key="aqi", label="Air quality", score=80.0, raw_value=1, unit="u", status=FactorStatus.OK),
    }

    result = aggregator.compute_overall(
        results, UserProfile(age=25)
    )

    assert result.weights_used["social_hub_proximity"] > result.weights_used["aqi"]
    assert result.weights_used["social_hub_proximity"] + result.weights_used["aqi"] == pytest.approx(1.0)
    assert result.personalization_applied != []


def test_no_profile_leaves_weights_exactly_at_registry_defaults(monkeypatch):
    defs = [
        FactorDefinition("social_hub_proximity", "Social hub", 0.5, True, vendors=[]),
        FactorDefinition("aqi", "Air quality", 0.5, True, vendors=[]),
    ]
    monkeypatch.setattr(aggregator, "FACTOR_REGISTRY", defs)
    results = {
        "social_hub_proximity": FactorResult(
            key="social_hub_proximity", label="Social hub", score=80.0, raw_value=1, unit="u", status=FactorStatus.OK
        ),
        "aqi": FactorResult(key="aqi", label="Air quality", score=80.0, raw_value=1, unit="u", status=FactorStatus.OK),
    }

    result = aggregator.compute_overall(results, None)

    assert result.weights_used == {"social_hub_proximity": 0.5, "aqi": 0.5}
    assert result.personalization_applied == []


def test_elderly_profile_boosts_healthcare_religious_and_aqi(monkeypatch):
    defs = [
        FactorDefinition("healthcare_proximity", "Healthcare", 0.25, True, vendors=[]),
        FactorDefinition("religious_site_proximity", "Religious", 0.25, True, vendors=[]),
        FactorDefinition("aqi", "Air quality", 0.25, True, vendors=[]),
        FactorDefinition("social_hub_proximity", "Social hub", 0.25, True, vendors=[]),
    ]
    monkeypatch.setattr(aggregator, "FACTOR_REGISTRY", defs)
    results = {
        d.key: FactorResult(key=d.key, label=d.label, score=80.0, raw_value=1, unit="u", status=FactorStatus.OK)
        for d in defs
    }

    result = aggregator.compute_overall(results, UserProfile(age=70))

    assert result.weights_used["healthcare_proximity"] > result.weights_used["social_hub_proximity"]
    assert result.weights_used["religious_site_proximity"] > result.weights_used["social_hub_proximity"]
    assert result.weights_used["aqi"] > result.weights_used["social_hub_proximity"]
    assert sum(result.weights_used.values()) == pytest.approx(1.0)
    assert len(result.personalization_applied) == 3  # healthcare, religious, aqi rules all fire


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
