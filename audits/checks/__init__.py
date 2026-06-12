"""Import audit check modules so decorators populate the registry."""
from audits.checks import data_quality, radar_quality, system_health, valuation_quality

__all__ = [
    "data_quality",
    "radar_quality",
    "system_health",
    "valuation_quality",
]
