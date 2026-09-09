from __future__ import annotations

from domain.models import UserProfile, WeightAdjustmentRule

YOUNG_AGE_MAX = 30
ELDERLY_AGE_MIN = 60


def _is_young(profile: UserProfile) -> bool:
    return profile.age is not None and profile.age <= YOUNG_AGE_MAX


def _is_elderly(profile: UserProfile) -> bool:
    return profile.age is not None and profile.age >= ELDERLY_AGE_MIN


# Declarative, extensible on purpose - adding a new personalization dimension later
# (e.g. has_children, mobility_needs) means adding rules here, not touching the
# aggregator. Several rules can fire on the same factor; multipliers stack before
# renormalization.
PERSONALIZATION_RULES: list[WeightAdjustmentRule] = [
    WeightAdjustmentRule(
        factor_key="social_hub_proximity",
        multiplier=2.5,
        applies=_is_young,
        reason=f"Age {YOUNG_AGE_MAX} or under: social hub (nightlife/cafe) proximity weighted higher",
    ),
    WeightAdjustmentRule(
        factor_key="religious_site_proximity",
        multiplier=3.0,
        applies=_is_elderly,
        reason=f"Age {ELDERLY_AGE_MIN}+: proximity to a place of worship weighted higher",
    ),
    WeightAdjustmentRule(
        factor_key="healthcare_proximity",
        multiplier=2.5,
        applies=_is_elderly,
        reason=f"Age {ELDERLY_AGE_MIN}+: healthcare proximity weighted higher",
    ),
    WeightAdjustmentRule(
        factor_key="aqi",
        multiplier=1.3,
        applies=_is_elderly,
        reason=f"Age {ELDERLY_AGE_MIN}+: air quality weighted higher (greater health sensitivity)",
    ),
    WeightAdjustmentRule(
        factor_key="daily_essentials",
        multiplier=2.0,
        applies=_is_elderly,
        reason=f"Age {ELDERLY_AGE_MIN}+: walkable groceries, pharmacy and banking weighted higher",
    ),
    WeightAdjustmentRule(
        factor_key="connectivity",
        multiplier=1.6,
        applies=_is_young,
        reason=f"Age {YOUNG_AGE_MAX} or under: public transport connectivity weighted higher",
    ),
]


def adjusted_weights(
    base_weights: dict[str, float], profile: UserProfile | None
) -> tuple[dict[str, float], list[str]]:
    """Applies matching rules on top of base_weights, then renormalizes back to sum
    to 1.0 so personalization only ever shifts relative emphasis, never the range the
    composite score can land in. Returns (weights, reasons) - reasons lists which
    rules actually fired, for transparency in the API response.

    With profile=None (the common case), returns base_weights completely unchanged
    and an empty reasons list - personalization is opt-in, never mandatory.
    """
    if profile is None:
        return dict(base_weights), []

    adjusted = dict(base_weights)
    reasons: list[str] = []
    for rule in PERSONALIZATION_RULES:
        if rule.factor_key not in adjusted:
            continue
        if rule.applies(profile):
            adjusted[rule.factor_key] *= rule.multiplier
            reasons.append(rule.reason)

    total = sum(adjusted.values())
    if total <= 0:
        return dict(base_weights), []
    normalized = {k: v / total for k, v in adjusted.items()}
    return normalized, reasons
