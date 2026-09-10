from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas import (
    CompareRequest,
    CompareResponse,
    FactorComparisonResponse,
    FactorResponse,
    LocationResponse,
    ScoreRequest,
    ScoreResponse,
    ShareRequest,
    ShareResolveResponse,
    ShareResponse,
    UserProfileRequest,
)
from domain.models import FactorResult, Religion, TransportPreference, UserProfile
from service import aggregator, comparison
from service.share_codec import ShareCodeError, SharePayload, decode, encode

router = APIRouter()


def _to_domain_profile(profile: UserProfileRequest | None) -> UserProfile | None:
    """None when nothing was supplied, so an empty profile object from a client is
    indistinguishable from no personalization at all."""
    if profile is None:
        return None
    built = UserProfile(
        age=profile.age,
        religion=Religion(profile.religion) if profile.religion else None,
        transport_preference=(
            TransportPreference(profile.transport_preference) if profile.transport_preference else None
        ),
    )
    return None if built.is_empty() else built


def _to_factor_responses(factor_results: dict[str, FactorResult]) -> dict[str, FactorResponse]:
    return {
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


async def _score_one(lat: float, lng: float, profile: UserProfile | None) -> tuple[ScoreResponse, dict[str, FactorResult]]:
    factor_results = await aggregator.compute_all(lat, lng, profile)
    overall = aggregator.compute_overall(factor_results, profile)
    response = ScoreResponse(
        overall_score=overall.score,
        location=LocationResponse(lat=lat, lng=lng),
        factors=_to_factor_responses(factor_results),
        weights_used=overall.weights_used,
        unverified_factors=overall.unverified,
        personalization_applied=overall.personalization_applied,
        excluded_factors=overall.excluded,
    )
    return response, factor_results


@router.post("/api/score", response_model=ScoreResponse)
async def score(request: ScoreRequest) -> ScoreResponse:
    response, _ = await _score_one(request.lat, request.lng, _to_domain_profile(request.profile))
    return response


@router.post("/api/compare", response_model=CompareResponse)
async def compare(request: CompareRequest) -> CompareResponse:
    """Scores several locations under one profile and reports who wins each factor.

    Each location is scored by exactly the same path /api/score uses, so a comparison
    can never disagree with the individual scores a user might open alongside it.
    """
    profile = _to_domain_profile(request.profile)
    scored = [await _score_one(loc.lat, loc.lng, profile) for loc in request.locations]
    responses = [s[0] for s in scored]

    result = comparison.compare(
        [s[1] for s in scored], [r.overall_score for r in responses]
    )
    return CompareResponse(
        locations=responses,
        overall_winner=result.overall_winner,
        overall_difference=result.overall_difference,
        factors={
            key: FactorComparisonResponse(
                label=value.label,
                scores=value.scores,
                winner=value.winner,
                difference=value.difference,
            )
            for key, value in result.factors.items()
        },
    )


@router.post("/api/share", response_model=ShareResponse)
def create_share(request: ShareRequest) -> ShareResponse:
    """Packs a view into a short code.

    The code carries the payload rather than pointing at a stored row, so there is no
    database to run and no link that stops working once a row is cleaned up or a free
    instance restarts. See service/share_codec.py.
    """
    profile = _to_domain_profile(request.profile)
    try:
        code = encode(
            SharePayload(
                locations=[(loc.lat, loc.lng) for loc in request.locations],
                age=profile.age if profile else None,
                religion=profile.religion.value if profile and profile.religion else None,
                transport_preference=(
                    profile.transport_preference.value
                    if profile and profile.transport_preference
                    else None
                ),
            )
        )
    except ShareCodeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ShareResponse(code=code)


@router.get("/api/share/{code}", response_model=ShareResolveResponse)
def resolve_share(code: str) -> ShareResolveResponse:
    try:
        payload = decode(code)
    except ShareCodeError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    has_profile = (
        payload.age is not None
        or payload.religion is not None
        or payload.transport_preference is not None
    )
    return ShareResolveResponse(
        locations=[LocationResponse(lat=lat, lng=lng) for lat, lng in payload.locations],
        profile=(
            UserProfileRequest(
                age=payload.age,
                religion=payload.religion,
                transport_preference=payload.transport_preference,
            )
            if has_profile
            else None
        ),
    )
