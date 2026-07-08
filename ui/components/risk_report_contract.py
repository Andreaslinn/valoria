"""Pure shadow contract for context-aware Risk Report normalization."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class AnalysisContext(StrEnum):
    PROPERTY_VALUATION = "PROPERTY_VALUATION"
    LISTING_ANALYSIS = "LISTING_ANALYSIS"


@dataclass(frozen=True)
class EvidenceFlag:
    code: str
    raw_codes: tuple[str, ...]
    category: str
    severity: str
    score_effects: tuple[str, ...]
    user_title: str
    user_message: str
    user_visible: bool = True


@dataclass(frozen=True)
class ContextualMissingField:
    field: str
    section: str
    required_for: str
    user_title: str


@dataclass(frozen=True)
class NotApplicableField:
    field: str
    reason: str


@dataclass(frozen=True)
class TechnicalHidden:
    code: str
    raw_codes: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ScoreSummary:
    name: str
    value: float | None = None
    label: str | None = None


@dataclass(frozen=True)
class ReportSection:
    code: str
    title: str
    items: tuple[str, ...] = ()


@dataclass(frozen=True)
class RiskReportInput:
    analysis_context: AnalysisContext
    valuation_core: dict[str, Any] = field(default_factory=dict)
    valuation_quality: dict[str, Any] = field(default_factory=dict)
    market_context: dict[str, Any] = field(default_factory=dict)
    asset_profile: dict[str, Any] = field(default_factory=dict)
    listing_context: dict[str, Any] | None = None
    listing_evidence: dict[str, Any] | None = None
    price_opportunity: dict[str, Any] | None = None
    raw_warnings: tuple[str, ...] = ()
    technical_provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskReportOutput:
    analysis_context: str
    report_type: str
    headline_score_name: str
    valuation_core: dict[str, Any]
    valuation_quality: dict[str, Any]
    market_context: dict[str, Any]
    asset_profile: dict[str, Any]
    listing_context: dict[str, Any] | None
    listing_evidence: dict[str, Any] | None
    price_opportunity: dict[str, Any] | None
    evidence_flags: tuple[EvidenceFlag, ...]
    contextual_missing_fields: tuple[ContextualMissingField, ...]
    not_applicable: tuple[NotApplicableField, ...]
    technical_hidden: tuple[TechnicalHidden, ...]
    score_summary: ScoreSummary
    report_sections: tuple[ReportSection, ...]
    future_excluded_from_score: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceFlagDefinition:
    code: str
    category: str
    severity: str
    score_effects: tuple[str, ...]
    title: str
    message: str
    contexts: tuple[AnalysisContext, ...]
    user_visible: bool = True
    technical_only: bool = False


@dataclass(frozen=True)
class EvidenceNormalizationResult:
    evidence_flags: tuple[EvidenceFlag, ...]
    not_applicable: tuple[NotApplicableField, ...]
    technical_hidden: tuple[TechnicalHidden, ...]


LISTING_ONLY_FIELDS = (
    "published_price",
    "discount_pct",
    "listing_id",
    "url",
    "source",
    "watchlist_state",
    "price_history_series",
    "price_drop_event",
    "alert_state",
    "days_on_market",
    "listing_url_lookup_status",
)

FUTURE_EXCLUDED_FROM_SCORE = (
    "days_on_market",
    "liquidity",
    "legal_external_risk",
    "market_map_heat_zones",
    "portfolio_avm_delta",
    "geographic_microzone",
)

TECHNICAL_PROVENANCE_FIELDS = (
    "engine_results",
    "consensus_summary",
    "surface_adjustment_weight",
    "surface_adjustment_reason",
    "canonical_price_basis",
    "price_history_artifact",
    "uf_rate_source",
    "uf_rate_is_fallback",
    "raw_error_messages",
    "engine_name",
    "engine_version",
)

_PROPERTY_VALUATION_LISTING_WARNING_CODES = {
    "published_price_not_provided",
    "url_missing",
    "listing_url_missing",
    "listing_id_missing",
    "watchlist_unavailable",
    "publication_history_missing",
    "listing_activity_missing",
    "price_history_missing",
    "discount_unavailable",
}

_FLAG_DEFINITIONS = {
    "limited_comparable_sample": EvidenceFlagDefinition(
        code="limited_comparable_sample",
        category="market_support",
        severity="medium",
        score_effects=("reduce_valuation_confidence_score", "reduce_market_context_score"),
        title="Muestra comparable limitada",
        message="La estimacion usa pocos comparables utiles para este segmento. Conviene leer el resultado como referencial.",
        contexts=(AnalysisContext.PROPERTY_VALUATION, AnalysisContext.LISTING_ANALYSIS),
    ),
    "single_source_evidence": EvidenceFlagDefinition(
        code="single_source_evidence",
        category="market_support",
        severity="medium",
        score_effects=("reduce_market_context_score", "reduce_valuation_confidence_score"),
        title="Evidencia concentrada en una fuente",
        message="La muestra proviene de una fuente dominante, por lo que el soporte de mercado es menos diverso.",
        contexts=(AnalysisContext.PROPERTY_VALUATION, AnalysisContext.LISTING_ANALYSIS),
    ),
    "limited_geographic_precision": EvidenceFlagDefinition(
        code="limited_geographic_precision",
        category="location_quality",
        severity="medium",
        score_effects=("reduce_valuation_confidence_score", "reduce_investment_score"),
        title="Precision geografica limitada",
        message="La ubicacion o la ubicacion de los comparables no esta completamente precisa. Esto puede afectar la lectura por microzona.",
        contexts=(AnalysisContext.PROPERTY_VALUATION, AnalysisContext.LISTING_ANALYSIS),
    ),
    "weak_microzone_support": EvidenceFlagDefinition(
        code="weak_microzone_support",
        category="location_quality",
        severity="medium",
        score_effects=("reduce_investment_score", "reduce_market_context_score"),
        title="Microzona con soporte debil",
        message="La lectura de microzona existe, pero aun no tiene suficiente soporte para tratarla como evidencia fuerte.",
        contexts=(AnalysisContext.PROPERTY_VALUATION, AnalysisContext.LISTING_ANALYSIS),
    ),
    "high_price_dispersion": EvidenceFlagDefinition(
        code="high_price_dispersion",
        category="valuation_quality",
        severity="medium",
        score_effects=("reduce_valuation_confidence_score", "reduce_market_context_score"),
        title="Precios comparables dispersos",
        message="Los precios por metro cuadrado varian mas de lo normal. La estimacion debe interpretarse con un rango mas amplio.",
        contexts=(AnalysisContext.PROPERTY_VALUATION, AnalysisContext.LISTING_ANALYSIS),
    ),
    "extreme_price_dispersion": EvidenceFlagDefinition(
        code="extreme_price_dispersion",
        category="valuation_quality",
        severity="high",
        score_effects=("reduce_valuation_confidence_score", "reduce_investment_score"),
        title="Alta dispersion de valor",
        message="La evidencia disponible muestra diferencias importantes entre referencias. Esto aumenta la incertidumbre de decision.",
        contexts=(AnalysisContext.PROPERTY_VALUATION, AnalysisContext.LISTING_ANALYSIS),
    ),
    "near_duplicate_evidence": EvidenceFlagDefinition(
        code="near_duplicate_evidence",
        category="market_support",
        severity="low",
        score_effects=("reduce_market_context_score",),
        title="Comparables poco diversos",
        message="Parte de la muestra parece repetida o muy similar. El soporte de mercado efectivo puede ser menor que el conteo bruto.",
        contexts=(AnalysisContext.PROPERTY_VALUATION, AnalysisContext.LISTING_ANALYSIS),
    ),
    "limited_land_area_evidence": EvidenceFlagDefinition(
        code="limited_land_area_evidence",
        category="asset_profile",
        severity="medium",
        score_effects=("reduce_valuation_confidence_score", "reduce_investment_score"),
        title="Terreno con evidencia limitada",
        message="Para casas, la evidencia de terreno no es suficientemente fuerte. La comparacion puede depender demasiado de superficie construida.",
        contexts=(AnalysisContext.PROPERTY_VALUATION, AnalysisContext.LISTING_ANALYSIS),
    ),
    "sparse_segment_bucket": EvidenceFlagDefinition(
        code="sparse_segment_bucket",
        category="market_support",
        severity="medium",
        score_effects=("reduce_market_context_score", "reduce_valuation_confidence_score"),
        title="Segmento con cobertura exploratoria",
        message="Hay datos para el segmento, pero la cobertura aun es beta o parcial. Usar como apoyo, no como unica senal.",
        contexts=(AnalysisContext.PROPERTY_VALUATION, AnalysisContext.LISTING_ANALYSIS),
    ),
    "published_price_missing": EvidenceFlagDefinition(
        code="published_price_missing",
        category="listing_evidence",
        severity="high",
        score_effects=("reduce_listing_evidence_score", "block_discount_calculation"),
        title="Precio publicado no disponible",
        message="No hay precio publicado suficiente para calcular descuento u oportunidad de negociacion.",
        contexts=(AnalysisContext.LISTING_ANALYSIS,),
    ),
    "listing_identity_missing": EvidenceFlagDefinition(
        code="listing_identity_missing",
        category="listing_evidence",
        severity="medium",
        score_effects=("reduce_listing_evidence_score",),
        title="Publicacion no identificada completamente",
        message="Falta URL o identificador confiable de la publicacion. Algunas senales de seguimiento quedan limitadas.",
        contexts=(AnalysisContext.LISTING_ANALYSIS,),
    ),
    "listing_activity_missing": EvidenceFlagDefinition(
        code="listing_activity_missing",
        category="listing_evidence",
        severity="medium",
        score_effects=("reduce_listing_evidence_score", "reduce_listing_opportunity_score"),
        title="Historial de publicacion incompleto",
        message="No hay historial suficiente de actividad o precio para evaluar momentum de la publicacion.",
        contexts=(AnalysisContext.LISTING_ANALYSIS,),
    ),
    "published_price_quality_limited": EvidenceFlagDefinition(
        code="published_price_quality_limited",
        category="listing_evidence",
        severity="medium",
        score_effects=("reduce_listing_evidence_score",),
        title="Precio publicado con calidad limitada",
        message="El precio proviene de una conversion o fuente historica menos confiable. La lectura de descuento debe ser cauta.",
        contexts=(AnalysisContext.LISTING_ANALYSIS,),
    ),
    "price_surface_limited": EvidenceFlagDefinition(
        code="price_surface_limited",
        category="valuation_quality",
        severity="medium",
        score_effects=("reduce_valuation_confidence_score", "reduce_market_context_score"),
        title="Superficie de precios limitada",
        message="La referencia de superficie de precios existe, pero su cobertura o estabilidad no es suficientemente fuerte.",
        contexts=(AnalysisContext.PROPERTY_VALUATION, AnalysisContext.LISTING_ANALYSIS),
    ),
    "engine_or_consensus_diagnostic": EvidenceFlagDefinition(
        code="engine_or_consensus_diagnostic",
        category="technical_only",
        severity="high",
        score_effects=("hide_from_user",),
        title="Diagnostico tecnico de motor",
        message="Detalle interno de ejecucion. En reportes de usuario debe traducirse a calidad de estimacion o quedar oculto.",
        contexts=(AnalysisContext.PROPERTY_VALUATION, AnalysisContext.LISTING_ANALYSIS),
        user_visible=False,
        technical_only=True,
    ),
}

_RAW_TO_CANONICAL = {
    "low_comparable_count": "limited_comparable_sample",
    "low_data_mode": "limited_comparable_sample",
    "few_selected_comparables": "limited_comparable_sample",
    "single_source_comparables": "single_source_evidence",
    "poor_geocoding_comparables": "limited_geographic_precision",
    "weak_geolocation": "limited_geographic_precision",
    "weak_geocode_quality": "limited_geographic_precision",
    "low_geocode_precision": "limited_geographic_precision",
    "weak_microzone": "weak_microzone_support",
    "high_price_m2_dispersion": "high_price_dispersion",
    "high_dispersion": "high_price_dispersion",
    "price_surface_high_dispersion": "high_price_dispersion",
    "extreme_price_m2_dispersion": "extreme_price_dispersion",
    "near_duplicate_comparables": "near_duplicate_evidence",
    "house_land_area_weak": "limited_land_area_evidence",
    "sparse_m2_bucket": "sparse_segment_bucket",
    "limited_segment_sample": "sparse_segment_bucket",
    "beta_scope_exploratory": "sparse_segment_bucket",
    "beta_scope_no_data": "sparse_segment_bucket",
    "beta_scope_weak_data": "sparse_segment_bucket",
    "published_price_not_provided": "published_price_missing",
    "missing_price": "published_price_missing",
    "url_missing": "listing_identity_missing",
    "listing_url_missing": "listing_identity_missing",
    "listing_id_missing": "listing_identity_missing",
    "invalid_url": "listing_identity_missing",
    "unsupported_source": "listing_identity_missing",
    "watchlist_unavailable": "listing_activity_missing",
    "publication_history_missing": "listing_activity_missing",
    "listing_activity_missing": "listing_activity_missing",
    "price_history_missing": "listing_activity_missing",
    "legacy_uf_missing_price_uf": "published_price_quality_limited",
    "estimated_uf_not_strong": "published_price_quality_limited",
    "low_confidence_uf_not_strong": "published_price_quality_limited",
    "price_surface_low_confidence": "price_surface_limited",
    "surface_adjustment_risk_comuna": "price_surface_limited",
    "surface_adjustment_unavailable": "price_surface_limited",
    "engine_not_registered": "engine_or_consensus_diagnostic",
    "unexpected_error": "engine_or_consensus_diagnostic",
    "consensus_missing_calibrated_weights": "engine_or_consensus_diagnostic",
    "validation_error": "engine_or_consensus_diagnostic",
}


def normalize_analysis_context(value: Any) -> AnalysisContext:
    if isinstance(value, AnalysisContext):
        return value
    text = str(value or "").strip().upper()
    if text == AnalysisContext.LISTING_ANALYSIS.value:
        return AnalysisContext.LISTING_ANALYSIS
    return AnalysisContext.PROPERTY_VALUATION


def normalize_evidence_flags(
    raw_warnings: Iterable[Any],
    analysis_context: AnalysisContext | str,
) -> EvidenceNormalizationResult:
    context = normalize_analysis_context(analysis_context)
    grouped_raw: dict[str, list[str]] = {}
    not_applicable: list[NotApplicableField] = []
    technical_hidden: list[TechnicalHidden] = []

    for raw in _dedupe_strings(raw_warnings):
        canonical = _RAW_TO_CANONICAL.get(raw)
        if canonical is None:
            continue
        definition = _FLAG_DEFINITIONS[canonical]
        if context == AnalysisContext.PROPERTY_VALUATION and raw in _PROPERTY_VALUATION_LISTING_WARNING_CODES:
            not_applicable.append(NotApplicableField(field=raw, reason="listing_only_warning_not_required_for_property_valuation"))
            continue
        if definition.technical_only:
            technical_hidden.append(TechnicalHidden(code=canonical, raw_codes=(raw,), reason="technical_only_warning"))
            continue
        if context not in definition.contexts:
            not_applicable.append(NotApplicableField(field=raw, reason=f"not_applicable_to_{context.value.lower()}"))
            continue
        grouped_raw.setdefault(canonical, []).append(raw)

    evidence_flags = tuple(
        _flag_from_definition(_FLAG_DEFINITIONS[canonical], tuple(raw_codes))
        for canonical, raw_codes in grouped_raw.items()
    )
    return EvidenceNormalizationResult(
        evidence_flags=evidence_flags,
        not_applicable=tuple(not_applicable),
        technical_hidden=tuple(_merge_technical_hidden(technical_hidden)),
    )


def build_risk_report_contract_shadow(
    *,
    valuation_result: dict[str, Any] | None = None,
    valuation_payload: dict[str, Any] | None = None,
    lookup_result: dict[str, Any] | None = None,
    opportunity: dict[str, Any] | None = None,
    analysis_context: AnalysisContext | str | None = None,
) -> RiskReportOutput:
    """Build a normalized Risk Report contract without changing the HTML report."""
    valuation_result = valuation_result or {}
    valuation_payload = valuation_payload or {}
    lookup_result = lookup_result or {}
    opportunity = opportunity or {}
    context = _infer_context(analysis_context, valuation_payload, lookup_result, opportunity)
    source = _merged_source(valuation_result, valuation_payload, lookup_result, opportunity)

    raw_warnings = _collect_raw_warnings(source, lookup_result, opportunity)
    normalized_flags = normalize_evidence_flags(raw_warnings, context)
    technical_hidden = list(normalized_flags.technical_hidden)
    technical_hidden.extend(_technical_hidden_from_payload(source))

    valuation_core = _valuation_core(source)
    valuation_quality = _valuation_quality(source)
    market_context = _market_context(source)
    asset_profile = _asset_profile(source)

    listing_context = None
    listing_evidence = None
    price_opportunity = None
    not_applicable = list(normalized_flags.not_applicable)
    if context == AnalysisContext.LISTING_ANALYSIS:
        listing_context = _listing_context(source)
        listing_evidence = _listing_evidence(source)
        price_opportunity = _price_opportunity(source, valuation_core)
    else:
        not_applicable.extend(
            NotApplicableField(field=field, reason="listing_signal_not_required_for_property_valuation")
            for field in LISTING_ONLY_FIELDS
        )

    headline_score_name = (
        "listing_opportunity_score"
        if context == AnalysisContext.LISTING_ANALYSIS
        else "investment_score"
    )
    report_type = (
        "Listing Risk / Opportunity Report"
        if context == AnalysisContext.LISTING_ANALYSIS
        else "Investment Intelligence Report"
    )

    return RiskReportOutput(
        analysis_context=context.value,
        report_type=report_type,
        headline_score_name=headline_score_name,
        valuation_core=valuation_core,
        valuation_quality=valuation_quality,
        market_context=market_context,
        asset_profile=asset_profile,
        listing_context=listing_context,
        listing_evidence=listing_evidence,
        price_opportunity=price_opportunity,
        evidence_flags=normalized_flags.evidence_flags,
        contextual_missing_fields=tuple(_contextual_missing_fields(context, source, valuation_core, valuation_quality)),
        not_applicable=tuple(_dedupe_not_applicable(not_applicable)),
        technical_hidden=tuple(_merge_technical_hidden(technical_hidden)),
        score_summary=ScoreSummary(name=headline_score_name),
        report_sections=tuple(_report_sections(context)),
        future_excluded_from_score=FUTURE_EXCLUDED_FROM_SCORE,
    )


def _flag_from_definition(definition: EvidenceFlagDefinition, raw_codes: tuple[str, ...]) -> EvidenceFlag:
    return EvidenceFlag(
        code=definition.code,
        raw_codes=raw_codes,
        category=definition.category,
        severity=definition.severity,
        score_effects=definition.score_effects,
        user_title=definition.title,
        user_message=definition.message,
        user_visible=definition.user_visible,
    )


def _infer_context(
    explicit: AnalysisContext | str | None,
    valuation_payload: dict[str, Any],
    lookup_result: dict[str, Any],
    opportunity: dict[str, Any],
) -> AnalysisContext:
    if explicit is not None:
        return normalize_analysis_context(explicit)
    if opportunity:
        return AnalysisContext.LISTING_ANALYSIS
    listing_data = lookup_result.get("listing_data") if isinstance(lookup_result.get("listing_data"), dict) else {}
    markers = (
        valuation_payload.get("url"),
        valuation_payload.get("source"),
        valuation_payload.get("listing_id"),
        lookup_result.get("url"),
        lookup_result.get("source"),
        lookup_result.get("listing_id"),
        listing_data.get("url"),
        listing_data.get("source"),
        listing_data.get("listing_id"),
    )
    if any(_has_value(value) for value in markers):
        return AnalysisContext.LISTING_ANALYSIS
    return AnalysisContext.PROPERTY_VALUATION


def _merged_source(
    valuation_result: dict[str, Any],
    valuation_payload: dict[str, Any],
    lookup_result: dict[str, Any],
    opportunity: dict[str, Any],
) -> dict[str, Any]:
    listing_data = lookup_result.get("listing_data") if isinstance(lookup_result.get("listing_data"), dict) else {}
    return {**valuation_payload, **listing_data, **lookup_result, **opportunity, **valuation_result}


def _collect_raw_warnings(
    source: dict[str, Any],
    lookup_result: dict[str, Any],
    opportunity: dict[str, Any],
) -> tuple[str, ...]:
    warnings: list[Any] = []
    for key in (
        "warnings",
        "confidence_risk_flags",
        "comparable_quality_flags",
        "beta_scope_flags",
        "risk_flags",
    ):
        warnings.extend(_as_list(source.get(key)))
        warnings.extend(_as_list(opportunity.get(key)))
    warnings.extend(_as_list(lookup_result.get("warnings")))
    return tuple(_dedupe_strings(warnings))


def _technical_hidden_from_payload(source: dict[str, Any]) -> tuple[TechnicalHidden, ...]:
    hidden: list[TechnicalHidden] = []
    for field_name in TECHNICAL_PROVENANCE_FIELDS:
        if _has_value(source.get(field_name)):
            hidden.append(
                TechnicalHidden(
                    code=field_name,
                    raw_codes=(field_name,),
                    reason="technical_provenance_hidden_from_user_report",
                )
            )
    if _has_value(source.get("safe_error_message")) or _has_value(source.get("error")):
        hidden.append(
            TechnicalHidden(
                code="raw_error_messages",
                raw_codes=("safe_error_message", "error"),
                reason="raw_error_hidden_from_user_report",
            )
        )
    return tuple(hidden)


def _valuation_core(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "estimated_value": _first_present(
            source,
            "estimated_value_uf",
            "estimated_price_uf",
            "estimated_value_clp",
            "estimated_price_clp",
        ),
        "valuation_range": {
            "low_uf": source.get("price_range_low_uf"),
            "high_uf": source.get("price_range_high_uf"),
            "low_clp": source.get("price_range_low_clp"),
            "high_clp": source.get("price_range_high_clp"),
        },
        "price_m2": _first_present(source, "price_m2_uf", "price_per_m2_uf", "price_per_m2"),
    }


def _valuation_quality(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "confidence_contract": {
            "label": _first_present(source, "confidence_label", "confidence"),
            "score": source.get("confidence_score"),
            "reasons": _as_list(source.get("confidence_reasons")),
        },
        "comparable_count": _first_present(source, "comparable_count", "comparables_used", "n_comparables"),
        "comparable_quality_level": source.get("comparable_quality_level"),
        "beta_scope": {
            "status": source.get("beta_scope_status"),
            "message": source.get("beta_scope_message"),
            "metrics": source.get("beta_scope_metrics"),
        },
        "price_surface_context": source.get("price_surface_context") or source.get("surface"),
    }


def _market_context(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "comuna": source.get("comuna"),
        "microzone_match_ratio": _first_present(source, "microzone_match_ratio", "same_microzone_ratio"),
        "segment_depth": _first_present(source, "segment_depth", "segment_sample_count"),
        "m2_bucket_coverage": source.get("m2_bucket_coverage"),
    }


def _asset_profile(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "property_type": source.get("property_type"),
        "area_profile": {
            "m2": _first_present(source, "m2", "built_area_m2"),
            "built_area_m2": source.get("built_area_m2"),
            "land_area_m2": source.get("land_area_m2"),
            "usable_area_m2": source.get("usable_area_m2"),
        },
        "physical_attributes": {
            "bedrooms": _first_present(source, "bedrooms", "dormitorios"),
            "bathrooms": _first_present(source, "bathrooms", "banos"),
            "parking": _first_present(source, "parking", "parking_spaces", "estacionamientos"),
        },
    }


def _listing_context(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "listing_id": source.get("listing_id"),
        "url": source.get("url"),
        "source": source.get("source"),
        "status": source.get("status"),
        "listing_url_lookup_status": source.get("listing_url_lookup_status") or source.get("status"),
    }


def _listing_evidence(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "published_price": _first_present(
            source,
            "published_price",
            "precio_publicado_uf",
            "precio_publicado_clp",
            "price_uf",
            "price_clp",
        ),
        "canonical_price_basis_label": _canonical_price_basis_label(source.get("canonical_price_basis")),
        "watchlist_state": source.get("watchlist_state"),
        "price_history_series": source.get("price_history_series") or source.get("price_history"),
        "alert_state": source.get("alert_state"),
    }


def _price_opportunity(source: dict[str, Any], valuation_core: dict[str, Any]) -> dict[str, Any]:
    return {
        "published_price": _first_present(
            source,
            "published_price",
            "precio_publicado_uf",
            "precio_publicado_clp",
            "price_uf",
            "price_clp",
        ),
        "estimated_value": valuation_core.get("estimated_value"),
        "discount_pct": source.get("discount_pct"),
        "price_drop_event": source.get("price_drop_event"),
    }


def _contextual_missing_fields(
    context: AnalysisContext,
    source: dict[str, Any],
    valuation_core: dict[str, Any],
    valuation_quality: dict[str, Any],
) -> list[ContextualMissingField]:
    checks = [
        ("comuna", source.get("comuna"), "market_context", "Comuna"),
        ("property_type", source.get("property_type"), "asset_profile", "Tipo de propiedad"),
        ("area_profile", _first_present(source, "built_area_m2", "m2"), "asset_profile", "Superficie construida"),
        ("estimated_value", valuation_core.get("estimated_value"), "valuation_core", "Valor estimado"),
        ("confidence_contract", valuation_quality.get("confidence_contract", {}).get("label"), "valuation_quality", "Confianza"),
        ("comparable_count", valuation_quality.get("comparable_count"), "valuation_quality", "Comparables"),
    ]
    if context == AnalysisContext.LISTING_ANALYSIS:
        checks.extend(
            [
                ("published_price", _price_opportunity(source, valuation_core).get("published_price"), "price_opportunity", "Precio publicado"),
                ("url", source.get("url"), "listing_context", "URL"),
                ("listing_id", source.get("listing_id"), "listing_evidence", "Listing ID"),
            ]
        )
    return [
        ContextualMissingField(field=field, section=section, required_for=context.value, user_title=title)
        for field, value, section, title in checks
        if not _has_value(value)
    ]


def _report_sections(context: AnalysisContext) -> list[ReportSection]:
    if context == AnalysisContext.LISTING_ANALYSIS:
        return [
            ReportSection("price_opportunity", "Precio publicado vs valor estimado"),
            ReportSection("valuation_confidence", "Confianza de tasacion"),
            ReportSection("listing_evidence", "Evidencia de publicacion"),
            ReportSection("market_support", "Soporte de mercado"),
            ReportSection("bottom_line", "Bottom Line"),
        ]
    return [
        ReportSection("valuation_core", "Valor estimado"),
        ReportSection("investment_score", "Investment Score"),
        ReportSection("valuation_confidence", "Confianza de tasacion"),
        ReportSection("market_support", "Soporte de mercado"),
        ReportSection("asset_profile", "Perfil del activo"),
        ReportSection("bottom_line", "Bottom Line"),
    ]


def _canonical_price_basis_label(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, dict):
        confidence = value.get("confidence") or value.get("price_uf_confidence")
        if confidence:
            return f"Precio publicado con calidad {confidence}"
    return "Precio publicado con provenance disponible"


def _first_present(source: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = source.get(key)
        if _has_value(value):
            return value
    return None


def _has_value(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, str) and value.strip().lower() in {"unknown", "desconocido", "n/a"}:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, int | float):
        return value > 0
    if isinstance(value, list | tuple | set | dict):
        return bool(value)
    return True


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list | tuple | set):
        return list(value)
    return [value]


def _dedupe_strings(values: Iterable[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return tuple(result)


def _dedupe_not_applicable(values: Iterable[NotApplicableField]) -> list[NotApplicableField]:
    result: list[NotApplicableField] = []
    seen: set[str] = set()
    for item in values:
        if item.field in seen:
            continue
        result.append(item)
        seen.add(item.field)
    return result


def _merge_technical_hidden(values: Iterable[TechnicalHidden]) -> list[TechnicalHidden]:
    grouped: dict[str, list[str]] = {}
    reasons: dict[str, str] = {}
    for item in values:
        grouped.setdefault(item.code, [])
        grouped[item.code].extend(item.raw_codes)
        reasons[item.code] = item.reason
    return [
        TechnicalHidden(code=code, raw_codes=_dedupe_strings(raw_codes), reason=reasons[code])
        for code, raw_codes in grouped.items()
    ]
