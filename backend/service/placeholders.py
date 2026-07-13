from __future__ import annotations

from domain.models import FactorResult, FactorStatus


def _stub(key: str, label: str) -> FactorResult:
    return FactorResult(
        key=key,
        label=label,
        score=None,
        raw_value=None,
        unit=None,
        status=FactorStatus.COMING_SOON,
    )


async def pollution_sources_stub(lat: float, lng: float) -> FactorResult:
    return _stub("pollution_sources", "Pollution sources")


async def noise_sources_stub(lat: float, lng: float) -> FactorResult:
    return _stub("noise_sources", "Noise sources")


async def wind_ventilation_stub(lat: float, lng: float) -> FactorResult:
    return _stub("wind_ventilation", "Wind / cross-ventilation")


async def crime_rate_stub(lat: float, lng: float) -> FactorResult:
    return _stub("crime_rate", "Crime rate")


async def locality_premium_stub(lat: float, lng: float) -> FactorResult:
    return _stub("locality_premium", "Locality premium-ness")


async def road_quality_stub(lat: float, lng: float) -> FactorResult:
    return _stub("road_quality", "Road width & condition")


async def drinking_water_stub(lat: float, lng: float) -> FactorResult:
    return _stub("drinking_water", "Drinking water availability & quality")


async def electricity_availability_stub(lat: float, lng: float) -> FactorResult:
    return _stub("electricity_availability", "Electricity availability")


async def bad_odour_stub(lat: float, lng: float) -> FactorResult:
    return _stub("bad_odour", "Bad odour")


async def price_per_sqm_stub(lat: float, lng: float) -> FactorResult:
    return _stub("price_per_sqm", "Price per m²")
