"""Shared constants and catalogs."""

from typing import Dict, Tuple

# Popular targets stored as (Right Ascension hours, Declination degrees)
POPULAR_TARGETS: Dict[str, Tuple[float, float]] = {
    "Andromeda Galaxy (M31)": (0.7122, 41.2692),
    "Orion Nebula (M42)": (5.5881, -5.3911),
    "Pleiades (M45)": (3.7883, 24.1167),
    "Polaris": (2.5303, 89.2641),
    "Vega": (18.6156, 38.7837),
    "Betelgeuse": (5.9195, 7.4071),
    "Sirius": (6.7525, -16.7161),
    "Altair": (19.8464, 8.8683),
}

SLEW_SPEED_LEVELS = [0.25, 0.5, 1.0, 2.0, 4.0]  # degrees per second
