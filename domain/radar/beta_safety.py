"""Beta-safe presentation rules for radar opportunities."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from core.assessment.beta_status import BetaStatus, normalize_beta_status


@dataclass(frozen=True)
class RadarSafetyAssessment:
    show: bool
    verdict: str
    message: str
    risk_flags: tuple[str, ...]


def assess_radar_safety(
    *,
    beta_scope_status: str | None,
    beta_scope_flags: Sequence[str] = (),
    comparable_quality_level: str | None,
    comparable_quality_flags: Sequence[str] = (),
    warnings: Sequence[str] = (),
) -> RadarSafetyAssessment:
    """Return beta-safe visibility and wording for a radar opportunity."""
    scope = normalize_beta_status(beta_scope_status, default="")
    quality = str(comparable_quality_level or "unknown").strip().lower()
    risk_flags = _risk_flags(beta_scope_flags, comparable_quality_flags, warnings)

    if scope == BetaStatus.NO_DATA:
        return RadarSafetyAssessment(
            show=False,
            verdict="no_data",
            message="No se muestra en Radar: el segmento no tiene datos suficientes.",
            risk_flags=risk_flags,
        )

    if scope in {BetaStatus.WEAK_DATA, BetaStatus.EXPLORATORY}:
        return RadarSafetyAssessment(
            show=True,
            verdict="revisar",
            message="Revisar manualmente: el segmento aun no tiene soporte suficiente para recomendacion fuerte.",
            risk_flags=risk_flags,
        )

    if quality in {"poor", "weak", "unknown"}:
        return RadarSafetyAssessment(
            show=True,
            verdict="revisar",
            message="Revisar manualmente: la calidad del set comparable es limitada.",
            risk_flags=risk_flags,
        )

    if scope == BetaStatus.STRONG_SAMPLE and quality == "strong":
        return RadarSafetyAssessment(
            show=True,
            verdict="senal_fuerte",
            message="Senal fuerte para beta privada, no recomendacion de compra automatica.",
            risk_flags=risk_flags,
        )

    return RadarSafetyAssessment(
        show=True,
        verdict="senal_beta",
        message="Senal beta con soporte de datos razonable; requiere revision humana.",
        risk_flags=risk_flags,
    )


def _risk_flags(*groups: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for group in groups:
        for item in group or ():
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
    return tuple(result[:8])
