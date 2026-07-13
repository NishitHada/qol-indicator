from __future__ import annotations

from domain.models import FactorDefinition, VendorAdapter
from service import air_quality, greenery_water, placeholders, temperature

FACTOR_REGISTRY: list[FactorDefinition] = [
    FactorDefinition(
        "greenery_proximity",
        "Greenery proximity",
        0.25,
        True,
        vendors=[VendorAdapter("osm-overpass", greenery_water.compute_greenery)],
    ),
    FactorDefinition(
        "water_proximity",
        "Water proximity",
        0.15,
        True,
        vendors=[VendorAdapter("osm-overpass", greenery_water.compute_water)],
    ),
    FactorDefinition(
        "aqi",
        "Air quality",
        0.35,
        True,
        vendors=[VendorAdapter("open-meteo", air_quality.compute)],
    ),
    FactorDefinition(
        "temperature",
        "Temperature",
        0.25,
        True,
        vendors=[VendorAdapter("open-meteo", temperature.compute)],
    ),
    # Deferred (v2) - implemented later, weight 0 until then.
    FactorDefinition(
        "pollution_sources",
        "Pollution sources",
        0.0,
        False,
        vendors=[VendorAdapter("stub", placeholders.pollution_sources_stub)],
    ),
    FactorDefinition(
        "noise_sources",
        "Noise sources",
        0.0,
        False,
        vendors=[VendorAdapter("stub", placeholders.noise_sources_stub)],
    ),
    FactorDefinition(
        "wind_ventilation",
        "Wind / cross-ventilation",
        0.0,
        False,
        vendors=[VendorAdapter("stub", placeholders.wind_ventilation_stub)],
    ),
    # Requested future extensions - same stub pattern, data source TBD.
    FactorDefinition(
        "crime_rate",
        "Crime rate",
        0.0,
        False,
        vendors=[VendorAdapter("stub", placeholders.crime_rate_stub)],
    ),
    FactorDefinition(
        "locality_premium",
        "Locality premium-ness",
        0.0,
        False,
        vendors=[VendorAdapter("stub", placeholders.locality_premium_stub)],
    ),
    FactorDefinition(
        "road_quality",
        "Road width & condition",
        0.0,
        False,
        vendors=[VendorAdapter("stub", placeholders.road_quality_stub)],
    ),
    FactorDefinition(
        "drinking_water",
        "Drinking water availability & quality",
        0.0,
        False,
        vendors=[VendorAdapter("stub", placeholders.drinking_water_stub)],
    ),
    FactorDefinition(
        "electricity_availability",
        "Electricity availability",
        0.0,
        False,
        vendors=[VendorAdapter("stub", placeholders.electricity_availability_stub)],
    ),
    FactorDefinition(
        "bad_odour",
        "Bad odour",
        0.0,
        False,
        vendors=[VendorAdapter("stub", placeholders.bad_odour_stub)],
    ),
    FactorDefinition(
        "price_per_sqm",
        "Price per m²",
        0.0,
        False,
        vendors=[VendorAdapter("stub", placeholders.price_per_sqm_stub)],
    ),
]
