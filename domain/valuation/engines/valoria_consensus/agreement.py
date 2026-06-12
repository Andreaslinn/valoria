"""Agreement diagnostics across engine estimates."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median


@dataclass(frozen=True)
class AgreementDiagnostics:
    level: str
    dispersion_pct: float
    max_difference_clp: Decimal
    max_relative_difference_pct: float
    discrepant_engines: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "level": self.level,
            "dispersion_pct": round(self.dispersion_pct, 4),
            "max_difference_clp": float(self.max_difference_clp),
            "max_relative_difference_pct": round(self.max_relative_difference_pct, 4),
            "discrepant_engines": list(self.discrepant_engines),
        }


def assess_agreement(
    estimates: dict[str, Decimal],
    *,
    moderate_threshold: float,
    weak_threshold: float,
    discrepant_threshold: float = 0.25,
) -> AgreementDiagnostics:
    if len(estimates) <= 1:
        return AgreementDiagnostics("strong", 0.0, Decimal("0"), 0.0, ())

    values = list(estimates.values())
    med = Decimal(str(median(float(value) for value in values)))
    if med <= 0:
        return AgreementDiagnostics("weak", 0.0, max(values) - min(values), 0.0, tuple(estimates))

    max_diff = max(values) - min(values)
    max_relative = float(max_diff / med)
    mean_value = sum(values) / Decimal(str(len(values)))
    dispersion = _coefficient_variation(values, mean_value)

    if max_relative <= moderate_threshold:
        level = "strong"
    elif max_relative <= weak_threshold:
        level = "moderate"
    else:
        level = "weak"

    discrepant = tuple(
        name
        for name, value in estimates.items()
        if abs(float((value - med) / med)) > discrepant_threshold
    )
    return AgreementDiagnostics(level, dispersion, max_diff, max_relative, discrepant)


def _coefficient_variation(values: list[Decimal], mean_value: Decimal) -> float:
    if mean_value <= 0 or len(values) <= 1:
        return 0.0
    variance = sum(float(value - mean_value) ** 2 for value in values) / len(values)
    return (variance ** 0.5) / float(mean_value)
