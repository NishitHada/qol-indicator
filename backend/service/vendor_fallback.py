from __future__ import annotations

import dataclasses

from domain.models import FactorDefinition, FactorResult, FactorStatus


async def resolve(definition: FactorDefinition, lat: float, lng: float) -> FactorResult:
    last_error: Exception | str | None = None
    for vendor in definition.vendors:
        try:
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
