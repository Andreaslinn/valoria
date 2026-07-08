"""UI taxonomy for backend valuation warnings."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValuationWarningDefinition:
    code: str
    category: str
    severity: str
    human_label: str
    short_description: str
    visible_by_default: bool = False
    technical_only: bool = True


@dataclass(frozen=True)
class ValuationWarningDetail:
    code: str
    category: str
    severity: str
    human_label: str
    short_description: str
    visible_by_default: bool
    technical_only: bool
    known: bool


@dataclass(frozen=True)
class ValuationWarningSummary:
    count: int
    data_quality_label: str
    headline: str
    details_label: str
    details: tuple[ValuationWarningDetail, ...]


WARNING_DEFINITIONS: dict[str, ValuationWarningDefinition] = {
    "poor_geocoding_comparables": ValuationWarningDefinition(
        code="poor_geocoding_comparables",
        category="geocoding",
        severity="medium",
        human_label="Comparables con ubicacion debil",
        short_description="Algunos comparables usados no tienen ubicacion suficientemente precisa.",
    ),
    "single_source_comparables": ValuationWarningDefinition(
        code="single_source_comparables",
        category="data_source",
        severity="medium",
        human_label="Comparables de una sola fuente",
        short_description="La estimacion usa principalmente datos provenientes de una fuente.",
    ),
    "weak_geolocation": ValuationWarningDefinition(
        code="weak_geolocation",
        category="geocoding",
        severity="medium",
        human_label="Ubicacion con precision limitada",
        short_description="La ubicacion disponible no permite una lectura geografica completamente precisa.",
    ),
    "weak_microzone": ValuationWarningDefinition(
        code="weak_microzone",
        category="location",
        severity="medium",
        human_label="Microzona limitada",
        short_description="No hay suficiente profundidad de datos a nivel microzona.",
    ),
    "surface_adjustment_risk_comuna": ValuationWarningDefinition(
        code="surface_adjustment_risk_comuna",
        category="valuation_quality",
        severity="medium",
        human_label="Ajuste por superficie con soporte comunal",
        short_description="La referencia de superficie usa soporte comunal y debe revisarse como detalle tecnico.",
    ),
    "surface_adjustment_unavailable": ValuationWarningDefinition(
        code="surface_adjustment_unavailable",
        category="valuation_quality",
        severity="low",
        human_label="Ajuste por superficie no disponible",
        short_description="No hubo suficiente soporte para aplicar un ajuste adicional por superficie.",
    ),
    "low_data_mode": ValuationWarningDefinition(
        code="low_data_mode",
        category="market_support",
        severity="medium",
        human_label="Muestra de datos limitada",
        short_description="La estimacion opera con una base de comparables acotada para este segmento.",
        visible_by_default=True,
        technical_only=False,
    ),
    "low_comparable_count": ValuationWarningDefinition(
        code="low_comparable_count",
        category="market_support",
        severity="medium",
        human_label="Pocos comparables disponibles",
        short_description="La estimacion usa pocos comparables utiles para la propiedad consultada.",
        visible_by_default=True,
        technical_only=False,
    ),
    "published_price_not_provided": ValuationWarningDefinition(
        code="published_price_not_provided",
        category="listing_data",
        severity="low",
        human_label="Precio publicado no informado",
        short_description="No se incluyo precio publicado en la solicitud de tasacion.",
    ),
    "unknown_property_type": ValuationWarningDefinition(
        code="unknown_property_type",
        category="asset_profile",
        severity="medium",
        human_label="Tipo de propiedad no clasificado",
        short_description="El tipo de propiedad no quedo completamente normalizado para el modelo.",
    ),
    "house_land_area_weak": ValuationWarningDefinition(
        code="house_land_area_weak",
        category="asset_profile",
        severity="medium",
        human_label="Terreno con evidencia limitada",
        short_description="Para casas, la evidencia de terreno no es suficientemente fuerte.",
    ),
    "high_price_m2_dispersion": ValuationWarningDefinition(
        code="high_price_m2_dispersion",
        category="valuation_quality",
        severity="medium",
        human_label="Precios comparables dispersos",
        short_description="Los precios por metro cuadrado varian mas de lo normal en la muestra.",
    ),
    "extreme_price_m2_dispersion": ValuationWarningDefinition(
        code="extreme_price_m2_dispersion",
        category="valuation_quality",
        severity="high",
        human_label="Alta dispersion de valor",
        short_description="La evidencia disponible muestra diferencias importantes entre referencias.",
    ),
    "near_duplicate_comparables": ValuationWarningDefinition(
        code="near_duplicate_comparables",
        category="market_support",
        severity="low",
        human_label="Comparables poco diversos",
        short_description="Parte de la muestra parece repetida o muy similar.",
    ),
}

_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


def summarize_valuation_warnings(raw_warnings: Any) -> ValuationWarningSummary:
    details = tuple(map_valuation_warnings(raw_warnings))
    count = len(details)
    quality = _quality_label(details)
    headline = f"Calidad de datos: {quality} - {count} detalles tecnicos" if count else "Calidad de datos: sin advertencias tecnicas"
    details_label = f"Ver detalles tecnicos ({count})" if count else "Sin detalles tecnicos"
    return ValuationWarningSummary(
        count=count,
        data_quality_label=quality,
        headline=headline,
        details_label=details_label,
        details=details,
    )


def map_valuation_warnings(raw_warnings: Any) -> list[ValuationWarningDetail]:
    details: list[ValuationWarningDetail] = []
    for code in _dedupe_warning_codes(raw_warnings):
        definition = WARNING_DEFINITIONS.get(code)
        if definition is None:
            details.append(
                ValuationWarningDetail(
                    code=code,
                    category="technical",
                    severity="low",
                    human_label="Warning tecnico no mapeado",
                    short_description="Codigo tecnico recibido desde backend. Revisar solo para auditoria o debugging.",
                    visible_by_default=False,
                    technical_only=True,
                    known=False,
                )
            )
            continue
        details.append(
            ValuationWarningDetail(
                code=definition.code,
                category=definition.category,
                severity=definition.severity,
                human_label=definition.human_label,
                short_description=definition.short_description,
                visible_by_default=definition.visible_by_default,
                technical_only=definition.technical_only,
                known=True,
            )
        )
    return details


def _quality_label(details: tuple[ValuationWarningDetail, ...]) -> str:
    if not details:
        return "alta"
    max_rank = max(_SEVERITY_RANK.get(detail.severity, 1) for detail in details)
    if max_rank >= 3:
        return "baja"
    if max_rank == 2:
        return "media"
    return "alta con observaciones"


def _dedupe_warning_codes(raw_warnings: Any) -> tuple[str, ...]:
    if raw_warnings is None or raw_warnings == "":
        return ()
    if isinstance(raw_warnings, str):
        values = [raw_warnings]
    elif isinstance(raw_warnings, list | tuple | set):
        values = list(raw_warnings)
    else:
        values = [raw_warnings]

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        code = str(value or "").strip()
        if not code or code in seen:
            continue
        result.append(code)
        seen.add(code)
    return tuple(result)
