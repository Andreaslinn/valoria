"""Contracts for market price trend outputs."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class PriceTrendPoint:
    month: str
    median_price_m2_uf: float
    sample_count: int


@dataclass(frozen=True)
class PriceTrend:
    status: str
    metric: str
    property_type: str
    comuna: str
    period_months: int
    points: tuple[PriceTrendPoint, ...] = ()
    latest_value: float | None = None
    previous_value: float | None = None
    change_pct: float | None = None
    direction: str = "unknown"
    coverage_count: int = 0
    source: str = "not_available"
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        data = asdict(self)
        data["points"] = [asdict(point) for point in self.points]
        return data


@dataclass(frozen=True)
class PriceTrendConfig:
    period_months: int = 12
    min_partial_points: int = 3
    min_available_points: int = 6
    min_samples_per_available_point: int = 3
    unsupported_property_types: tuple[str, ...] = field(default=("unknown", "land"))
