"""Adapter for the current production comparable valuation flow."""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal

from core.assessment.beta_status import beta_scope_warning_codes
from core.assessment.confidence import build_confidence_contract
from core.entities.listing import Listing, Property
from core.exceptions import InsufficientDataError, ValidationError
from core.normalization.property_type import normalize_property_type
from domain.geocoding.microzones import signals_from_value
from domain.geocoding.quality import normalized_precision_for
from domain.valuation.comparables import valuate_with_comparables
from domain.valuation.engines.contracts import (
    EngineComparable,
    EngineContext,
    EngineRequest,
    EngineResult,
    EngineStatus,
)
from domain.valuation.price_surface import (
    lookup_price_surface,
    maybe_apply_surface_adjustment,
    surface_warnings_for_estimate,
)
from services.formatting import price_clp_int


class ComparablesLegacyEngine:
    """Offline adapter around the exact legacy comparable engine.

    The adapter does not change filters, scoring, weights, canonical price mode,
    reliability, comparable quality, beta scope or price surface rules.
    """

    name = "comparables_legacy"
    version = "phase0b_legacy_v1"

    def valuate(self, request: EngineRequest, context: EngineContext) -> EngineResult:
        target = context.target
        if not isinstance(target, Property):
            return _failed(
                self.name,
                self.version,
                EngineStatus.VALIDATION_ERROR,
                "invalid_target",
                "comparables_legacy requires EngineContext.target as Property",
            )
        if context.uf_to_clp is None or context.uf_to_clp <= 0:
            return _failed(
                self.name,
                self.version,
                EngineStatus.VALIDATION_ERROR,
                "invalid_uf_rate",
                "comparables_legacy requires a positive UF to CLP rate",
            )

        uf_to_clp = Decimal(str(context.uf_to_clp))
        candidates = list(context.candidates)
        try:
            run = valuate_with_comparables(
                target,
                candidates,
                uf_to_clp,
                canonical_price_enabled=request.canonical_price_enabled,
            )
        except InsufficientDataError as exc:
            return _failed(
                self.name,
                self.version,
                EngineStatus.INSUFFICIENT_DATA,
                "insufficient_data",
                str(exc),
            )
        except ValidationError as exc:
            return _failed(
                self.name,
                self.version,
                EngineStatus.VALIDATION_ERROR,
                "validation_error",
                str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            return _failed(self.name, self.version, EngineStatus.ERROR, "unexpected_error", str(exc))

        result = run.result
        built_area = _built_area(target)
        if built_area is None or built_area <= 0:
            return _failed(
                self.name,
                self.version,
                EngineStatus.VALIDATION_ERROR,
                "invalid_built_area",
                "target built area must be positive",
            )

        warnings: list[str] = []
        warnings.extend(result.reliability_warnings)
        warnings.extend(result.comparable_quality_flags)
        warnings.extend(beta_scope_warning_codes(result.beta_scope_status))
        if result.comparables_used < 8:
            warnings.append("low_data_mode")
        if normalize_property_type(target) == "unknown":
            warnings.append("unknown_property_type")
        if not request.published_price_provided:
            warnings.append("published_price_not_provided")

        base_estimated_clp = price_clp_int(result.estimated_price)
        estimated_price_m2_clp = base_estimated_clp / built_area
        surface = lookup_price_surface(target, candidates)
        warnings.extend(
            warning
            for warning in surface_warnings_for_estimate(
                estimated_price_m2=estimated_price_m2_clp,
                surface=surface,
            )
            if warning != "price_surface_insufficient_data"
        )
        adjustment = maybe_apply_surface_adjustment(base_estimated_clp, surface, target)
        warnings.extend(adjustment.warnings)

        adjusted_estimated_clp = round(adjustment.adjusted_estimate)
        delta_clp = adjusted_estimated_clp - base_estimated_clp
        low_clp = max(0, price_clp_int(result.price_range_low) + delta_clp)
        high_clp = max(low_clp, price_clp_int(result.price_range_high) + delta_clp)
        confidence_contract = build_confidence_contract(
            score=result.confidence,
            base_score=result.base_confidence,
            reliability_warnings=result.reliability_warnings,
        )

        selected = tuple(
            EngineComparable(
                listing_id=listing.id,
                fingerprint=listing.fingerprint,
                score=round(score.value, 4),
                diagnostics={
                    "source": listing.source,
                    "comuna": listing.comuna,
                    "property_type": normalize_property_type(listing),
                    "distance_km": _distance_km(target, listing),
                    "geocode_precision": normalized_precision_for(listing),
                    "microzone_id": _microzone_id(listing),
                    "price_uf_source": listing.price_uf_source,
                    "price_uf_confidence": listing.price_uf_confidence,
                    "price_recovery_method": listing.price_recovery_method,
                },
            )
            for score, listing in run.scored_comparables
        )
        diagnostics = {
            "base_estimated_price_clp": base_estimated_clp,
            "base_estimated_price_uf": _clp_to_uf(base_estimated_clp, uf_to_clp),
            "range_low_uf": _clp_to_uf(low_clp, uf_to_clp),
            "range_high_uf": _clp_to_uf(high_clp, uf_to_clp),
            "price_m2_uf": _clp_to_uf(adjusted_estimated_clp, uf_to_clp) / built_area,
            "data_quality": result.comparable_quality_level,
            "explanation": "Legacy comparable weighted mean price/m2 with surface adjustment metadata.",
            "target": {
                "property_type": normalize_property_type(target),
                "geocode_precision": normalized_precision_for(target),
                "microzone_id": _microzone_id(target),
                "built_area_m2": _built_area(target),
                "land_area_m2": target.land_area_m2,
                "bedrooms": target.bedrooms,
                "bathrooms": target.bathrooms,
                "parking": target.parking,
            },
            "confidence_legacy_label": confidence_contract.legacy_confidence,
            "confidence_label": confidence_contract.confidence_label,
            "confidence_reasons": list(confidence_contract.confidence_reasons),
            "confidence_risk_flags": list(confidence_contract.confidence_risk_flags),
            "base_confidence": result.base_confidence.value if result.base_confidence else None,
            "reliability_warnings": list(result.reliability_warnings),
            "reliability_metrics": dict(result.reliability_metrics),
            "comparable_quality_level": result.comparable_quality_level,
            "comparable_quality_flags": list(result.comparable_quality_flags),
            "comparable_quality_metrics": dict(result.comparable_quality_metrics),
            "beta_scope_status": result.beta_scope_status,
            "beta_scope_flags": list(result.beta_scope_flags),
            "beta_scope_metrics": dict(result.beta_scope_metrics),
            "beta_scope_message": result.beta_scope_message,
            "surface_adjustment": {
                "applied": adjustment.adjustment_applied,
                "weight": adjustment.adjustment_weight,
                "reason": adjustment.adjustment_reason,
                "warnings": list(adjustment.warnings),
            },
            "surface": {
                "available": surface.available,
                "level_used": surface.level_used,
                "microzone_token": surface.microzone_token,
                "reason": surface.reason,
                "stats": asdict(surface.stats) if surface.stats else None,
            },
            "selected_comparable_fingerprints": [item.fingerprint for item in selected],
        }
        return EngineResult(
            engine_name=self.name,
            engine_version=self.version,
            status=EngineStatus.OK,
            estimated_price_clp=adjusted_estimated_clp,
            estimated_price_uf=_clp_to_uf(adjusted_estimated_clp, uf_to_clp),
            range_low_clp=low_clp,
            range_high_clp=high_clp,
            confidence=confidence_contract.confidence_score,
            comparables_used=result.comparables_used,
            warnings=tuple(_dedupe(warnings)),
            diagnostics=diagnostics,
            selected_comparables=selected,
            coverage_status=result.comparable_quality_level,
        )


def _failed(
    engine_name: str,
    engine_version: str,
    status: str,
    code: str,
    message: str,
) -> EngineResult:
    return EngineResult(
        engine_name=engine_name,
        engine_version=engine_version,
        status=status,
        warnings=(code,),
        diagnostics={},
        error_code=code,
        error_message=message,
    )


def _built_area(value: Property | Listing) -> float | None:
    return getattr(value, "built_area_m2", None) or getattr(value, "usable_area_m2", None) or value.m2


def _clp_to_uf(value: int | float | Decimal, uf_to_clp: Decimal) -> float:
    return round(float(Decimal(str(value)) / uf_to_clp), 2)


def _distance_km(target: Property, listing: Listing) -> float | None:
    if target.coordinates is None or listing.coordinates is None:
        return None
    return round(target.coordinates.distance_km(listing.coordinates), 4)


def _microzone_id(value: Property | Listing) -> str | None:
    metadata = getattr(value, "raw_metadata", None)
    if isinstance(metadata, dict):
        for key in ("microzone_id", "geo_microzone_id", "microzone"):
            raw = metadata.get(key)
            if raw is not None and str(raw).strip():
                return str(raw)
    signals = signals_from_value(value)
    tokens = [*signals.landmark_tokens]
    if signals.nearby_metro:
        tokens.append(f"metro:{signals.nearby_metro}")
    if signals.nearby_avenue:
        tokens.append(f"avenue:{signals.nearby_avenue}")
    if signals.intersection_hint:
        tokens.append(f"intersection:{signals.intersection_hint}")
    return "|".join(sorted(set(tokens))) or None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
