from __future__ import annotations

from fastapi import APIRouter

from api.schemas import FactorResponse, LocationResponse, ScoreRequest, ScoreResponse
from domain.models import UserProfile
from service import aggregator

router = APIRouter()


def _to_domain_profile(request: ScoreRequest) -> UserProfile | None:
    if request.profile is None or request.profile.age is None:
        return None
    return UserProfile(age=request.profile.age)


@router.post("/api/score", response_model=ScoreResponse)
async def score(request: ScoreRequest) -> ScoreResponse:
    profile = _to_domain_profile(request)
    factor_results = await aggregator.compute_all(request.lat, request.lng)
    overall, weights_used, unverified, personalization_applied = aggregator.compute_overall(
        factor_results, profile
    )

    factors = {
        key: FactorResponse(
            label=result.label,
            score=result.score,
            raw_value=result.raw_value,
            unit=result.unit,
            status=result.status.value,
            source=result.source,
            detail=result.detail,
        )
        for key, result in factor_results.items()
    }

    return ScoreResponse(
        overall_score=overall,
        location=LocationResponse(lat=request.lat, lng=request.lng),
        factors=factors,
        weights_used=weights_used,
        unverified_factors=unverified,
        personalization_applied=personalization_applied,
    )
