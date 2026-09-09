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
