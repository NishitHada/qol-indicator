from __future__ import annotations

import dataclasses

from domain.models import FactorDefinition, FactorResult, FactorStatus, UserProfile


async def resolve(
    definition: FactorDefinition, lat: float, lng: float, profile: UserProfile | None = None
) -> FactorResult:
    last_error: Exception | str | None = None
    for vendor in definition.vendors:
        try:
            # Vendors declare whether they read the profile, so a factor that measures
            # something different per profile gets it and the other twelve keep their
            # simpler signature.
            if vendor.profile_aware:
                result = await vendor.compute(lat, lng, profile)
            else:
                result = await vendor.compute(lat, lng)
        except Exception as e:
            last_error = e
            continue
        if result.status != FactorStatus.ERROR:
            return dataclasses.replace(result, source=vendor.name)
        last_error = result.detail or "vendor reported an error"

    return FactorResult(
        key=definition.key,
        label=definition.label,
        score=None,
        raw_value=None,
        unit=None,
        status=FactorStatus.ERROR,
        source=None,
        detail=f"All vendors failed: {last_error}",
    )
