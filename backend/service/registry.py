from __future__ import annotations

from domain.models import FactorDefinition, VendorAdapter
from service import (
    air_quality,
    connectivity,
    daily_essentials,
    greenery_water,
    healthcare_proximity,
    noise_sources,
    placeholders,
    pollution_sources,
    religious_site_proximity,
    social_hub_proximity,
    temperature,
    wind_ventilation,
)

# Weights across the 13 enabled factors below sum to 1.0 - the aggregator does a
# straight weighted sum, so they must be kept in balance whenever a factor is
# added/removed/reweighted here. Personalization (service/personalization.py) can
# shift these at request time, but always renormalizes back to 1.0 too.
FACTOR_REGISTRY: list[FactorDefinition] = [
    FactorDefinition(
        "greenery_proximity",
        "Greenery proximity",
        0.10,
        True,
        vendors=[VendorAdapter("osm-overpass", greenery_water.compute_greenery)],
    ),
    FactorDefinition(
        "water_proximity",
        "Water proximity",
        0.04,
        True,
        vendors=[VendorAdapter("osm-overpass", greenery_water.compute_water)],
    ),
    FactorDefinition(
        "aqi",
        "Air quality",
        0.15,
        True,
        vendors=[VendorAdapter("open-meteo", air_quality.compute)],
    ),
    FactorDefinition(
        "temperature",
        "Temperature",
        0.08,
        True,
        vendors=[VendorAdapter("open-meteo", temperature.compute)],
    ),
    FactorDefinition(
        "noise_sources",
        "Noise sources",
        0.09,
        True,
        vendors=[VendorAdapter("osm-overpass+adsb-lol", noise_sources.compute)],
    ),
    FactorDefinition(
        "healthcare_proximity",
        "Healthcare proximity",
        0.06,
        True,
        vendors=[VendorAdapter("osm-overpass", healthcare_proximity.compute)],
    ),
    FactorDefinition(
        "social_hub_proximity",
        "Social hub proximity",
        0.05,
        True,
        vendors=[VendorAdapter("osm-overpass", social_hub_proximity.compute)],
    ),
    FactorDefinition(
        "religious_site_proximity",
        "Religious site proximity",
        0.04,
        True,
        vendors=[VendorAdapter("osm-overpass", religious_site_proximity.compute)],
    ),
    FactorDefinition(
        "connectivity",
        "Public transport connectivity",
        0.13,
        True,
        vendors=[VendorAdapter("osm", connectivity.compute)],
    ),
    FactorDefinition(
        "daily_essentials",
        "Daily essentials nearby",
        0.11,
        True,
        vendors=[VendorAdapter("osm", daily_essentials.compute)],
    ),
    FactorDefinition(
        "pollution_sources",
        "Pollution sources",
        0.08,
        True,
        vendors=[VendorAdapter("osm", pollution_sources.compute_pollution)],
    ),
    FactorDefinition(
        "bad_odour",
        "Bad odour",
        0.03,
        True,
        vendors=[VendorAdapter("osm", pollution_sources.compute_odour)],
    ),
    FactorDefinition(
        "wind_ventilation",
        "Wind / cross-ventilation",
        0.04,
        True,
        vendors=[VendorAdapter("open-meteo", wind_ventilation.compute)],
    ),
    # Requested future extensions - same stub pattern, data source TBD. See the
    # "Not yet implemented" table in README.md for what each one is waiting on.
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
        "price_per_sqm",
        "Price per m²",
        0.0,
        False,
        vendors=[VendorAdapter("stub", placeholders.price_per_sqm_stub)],
    ),
]
