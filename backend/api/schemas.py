from __future__ import annotations

from pydantic import BaseModel, Field


class UserProfileRequest(BaseModel):
    """Every field is optional and defaults to unset - personalization only kicks in
    for the fields you actually provide."""

    age: int | None = Field(default=None, ge=0, le=120)


class ScoreRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    profile: UserProfileRequest | None = None


class FactorResponse(BaseModel):
    label: str
    score: float | None
    raw_value: float | None = None
    unit: str | None = None
    status: str
    source: str | None = None
    detail: str | None = None


class LocationResponse(BaseModel):
    lat: float
    lng: float


class ScoreResponse(BaseModel):
    overall_score: float
    location: LocationResponse
    factors: dict[str, FactorResponse]
    weights_used: dict[str, float]
    unverified_factors: list[str]
    personalization_applied: list[str]


class CompareRequest(BaseModel):
    """Two to four locations scored against each other under one profile.

    The profile is shared deliberately: a comparison only means something if both
    sides were weighted the same way.
    """

    locations: list[LocationResponse] = Field(min_length=2, max_length=4)
    profile: UserProfileRequest | None = None


class FactorComparisonResponse(BaseModel):
    label: str
    # One entry per location, in request order. null where that factor could not be
    # resolved for that location.
    scores: list[float | None]
    # Index of the clear winner, or null for a tie or an incomparable factor.
    winner: int | None = None
    # Gap between the best and the runner-up. null when there is nothing to compare.
    difference: float | None = None


class CompareResponse(BaseModel):
    locations: list[ScoreResponse]
    overall_winner: int | None = None
    overall_difference: float
    factors: dict[str, FactorComparisonResponse]


class ShareRequest(BaseModel):
    locations: list[LocationResponse] = Field(min_length=1, max_length=4)
    profile: UserProfileRequest | None = None


class ShareResponse(BaseModel):
    code: str


class ShareResolveResponse(BaseModel):
    locations: list[LocationResponse]
    profile: UserProfileRequest | None = None
