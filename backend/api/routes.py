from __future__ import annotations

from fastapi import APIRouter

from api.schemas import FactorResponse, LocationResponse, ScoreRequest, ScoreResponse
from service import aggregator

router = APIRouter()


@router.post("/api/score", response_model=ScoreResponse)
async def score(request: ScoreRequest) -> ScoreResponse:
    factor_results = await aggregator.compute_all(request.lat, request.lng)
    overall, weights_used, unverified = aggregator.compute_overall(factor_results)

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
    )
