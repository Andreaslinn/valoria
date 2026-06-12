"""Valuation use case facade."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.assessment.beta_status import beta_scope_warning_codes
from core.assessment.confidence import build_confidence_contract
from core.assessment.contracts import (
    BetaScopeMetricsPayload,
    ComparableOutPayload,
    ComparableQualityMetricsPayload,
    ValuationResultPayload,
)
from core.entities.listing import Listing, Property
from core.exceptions import ValidationError
from core.normalization.property_type import normalize_property_type as _normalize_property_type
from core.ports.listing_repo import ListingRepository
from core.ports.uf_service import UFService
from domain.valuation.comparables import valuate_with_comparables
from domain.valuation.price_surface import (
    lookup_price_surface,
    maybe_apply_surface_adjustment,
    surface_warnings_for_estimate,
)
from services.formatting import price_clp_int, price_uf_float
from services.uf_rate import require_real_uf_rate


@dataclass(frozen=True)
class ValuationInput:
    comuna: str
    property_type: str | None
    m2: float | None
    built_area_m2: float | None = None
    land_area_m2: float | None = None
    usable_area_m2: float | None = None
    dormitorios: int | None = None
    banos: int | None = None
    estacionamientos: int | None = None
    precio_publicado_uf: float | None = None
    precio_publicado_clp: int | None = None


@dataclass(frozen=True)
class ComparableDTO:
    listing_id: int | None
    title: str
    comuna: str
    price_uf: float
    price_clp: int
    m2: float
    built_area_m2: float | None
    land_area_m2: float | None
    usable_area_m2: float | None
    similarity: float
    url: str | None

    def to_payload(self) -> ComparableOutPayload:
        return {
            "listing_id": self.listing_id,
            "title": self.title,
            "comuna": self.comuna,
            "price_uf": self.price_uf,
            "price_clp": self.price_clp,
            "m2": self.m2,
            "built_area_m2": self.built_area_m2,
            "land_area_m2": self.land_area_m2,
            "usable_area_m2": self.usable_area_m2,
            "similarity": self.similarity,
            "url": self.url,
        }


@dataclass(frozen=True)
class ValuationDTO:
    base_estimated_price_uf: float | None
    base_estimated_price_clp: int | None
    estimated_price_uf: float | None
    estimated_price_clp: int | None
    price_range_low_uf: float | None
    price_range_high_uf: float | None
    price_range_low_clp: int | None
    price_range_high_clp: int | None
    confidence: str
    confidence_score: float | None
    confidence_label: str
    confidence_reasons: list[str]
    confidence_risk_flags: list[str]
    comparable_count: int
    price_m2_uf: float | None
    status: str
    warnings: list[str]
    comparable_quality_level: str | None
    comparable_quality_flags: list[str]
    comparable_quality_metrics: ComparableQualityMetricsPayload
    beta_scope_status: str | None
    beta_scope_flags: list[str]
    beta_scope_metrics: BetaScopeMetricsPayload
    beta_scope_message: str | None
    surface_adjustment_applied: bool
    surface_adjustment_weight: float
    surface_adjustment_reason: str
    comparables: list[ComparableDTO]

    def to_payload(self) -> ValuationResultPayload:
        return {
            "base_estimated_price_uf": self.base_estimated_price_uf,
            "base_estimated_price_clp": self.base_estimated_price_clp,
            "estimated_price_uf": self.estimated_price_uf,
            "estimated_price_clp": self.estimated_price_clp,
            "price_range_low_uf": self.price_range_low_uf,
            "price_range_high_uf": self.price_range_high_uf,
            "price_range_low_clp": self.price_range_low_clp,
            "price_range_high_clp": self.price_range_high_clp,
            "confidence": self.confidence,
            "confidence_score": self.confidence_score,
            "confidence_label": self.confidence_label,
            "confidence_reasons": list(self.confidence_reasons),
            "confidence_risk_flags": list(self.confidence_risk_flags),
            "comparable_count": self.comparable_count,
            "price_m2_uf": self.price_m2_uf,
            "status": self.status,
            "warnings": list(self.warnings),
            "comparable_quality_level": self.comparable_quality_level,
            "comparable_quality_flags": list(self.comparable_quality_flags),
            "comparable_quality_metrics": dict(self.comparable_quality_metrics),
            "beta_scope_status": self.beta_scope_status,
            "beta_scope_flags": list(self.beta_scope_flags),
            "beta_scope_metrics": dict(self.beta_scope_metrics),
            "beta_scope_message": self.beta_scope_message,
            "surface_adjustment_applied": self.surface_adjustment_applied,
            "surface_adjustment_weight": self.surface_adjustment_weight,
            "surface_adjustment_reason": self.surface_adjustment_reason,
            "comparables": [item.to_payload() for item in self.comparables],
        }


class ValuationService:
    def __init__(
        self,
        *,
        listing_repo: ListingRepository,
        uf_service: UFService,
    ) -> None:
        self._listing_repo = listing_repo
        self._uf_service = uf_service

    async def valuate_property(self, data: ValuationInput) -> ValuationDTO:
        property_type = _normalize_property_type(data.property_type)
        built_area_m2 = data.built_area_m2 or data.usable_area_m2 or data.m2
        usable_area_m2 = data.usable_area_m2 or built_area_m2 if property_type == "apartment" else data.usable_area_m2
        if built_area_m2 is None or built_area_m2 <= 0:
            raise ValidationError("m2, built_area_m2 o usable_area_m2 debe ser positivo")
        if property_type == "house" and data.land_area_m2 is not None and data.land_area_m2 <= 0:
            raise ValidationError("land_area_m2 debe ser positivo")

        uf_info = await require_real_uf_rate(self._uf_service)
        uf_to_clp = uf_info.rate
        target = Property(
            id=None,
            comuna=data.comuna,
            m2=built_area_m2,
            bedrooms=data.dormitorios or 0,
            bathrooms=data.banos or 0,
            parking=data.estacionamientos or 0,
            property_type=property_type,
            built_area_m2=built_area_m2,
            land_area_m2=data.land_area_m2,
            usable_area_m2=usable_area_m2,
        )
        candidates = await self._listing_repo.find_active_in_comuna(
            data.comuna,
            property_type=property_type,
        )

        valuation_run = valuate_with_comparables(target, candidates, uf_to_clp)
        result = valuation_run.result

        warnings: list[str] = []
        warnings.extend(result.reliability_warnings)
        warnings.extend(result.comparable_quality_flags)
        warnings.extend(_beta_scope_warning_codes(result.beta_scope_status))
        if result.comparables_used < 8:
            warnings.append("low_data_mode")
        if property_type == "unknown":
            warnings.append("unknown_property_type")
        if data.precio_publicado_uf is None and data.precio_publicado_clp is None:
            warnings.append("published_price_not_provided")
        estimated_price_m2_clp = price_clp_int(result.estimated_price) / built_area_m2
        surface = lookup_price_surface(target, candidates)
        warnings.extend(
            warning for warning in surface_warnings_for_estimate(
                estimated_price_m2=estimated_price_m2_clp,
                surface=surface,
            )
            if warning != "price_surface_insufficient_data"
        )
        base_estimated_clp = price_clp_int(result.estimated_price)
        adjustment = maybe_apply_surface_adjustment(
            base_estimated_clp,
            surface,
            target,
        )
        confidence_contract = build_confidence_contract(
            score=result.confidence,
            base_score=result.base_confidence,
            reliability_warnings=result.reliability_warnings,
        )
        warnings.extend(adjustment.warnings)
        adjusted_estimated_clp = int(round(adjustment.adjusted_estimate))
        delta_clp = adjusted_estimated_clp - base_estimated_clp
        low_clp = max(0, price_clp_int(result.price_range_low) + delta_clp)
        high_clp = max(low_clp, price_clp_int(result.price_range_high) + delta_clp)

        return ValuationDTO(
            base_estimated_price_uf=_clp_to_uf(base_estimated_clp, uf_to_clp),
            base_estimated_price_clp=base_estimated_clp,
            estimated_price_uf=_clp_to_uf(adjusted_estimated_clp, uf_to_clp),
            estimated_price_clp=adjusted_estimated_clp,
            price_range_low_uf=_clp_to_uf(low_clp, uf_to_clp),
            price_range_high_uf=_clp_to_uf(high_clp, uf_to_clp),
            price_range_low_clp=low_clp,
            price_range_high_clp=high_clp,
            confidence=confidence_contract.legacy_confidence,
            confidence_score=confidence_contract.confidence_score,
            confidence_label=confidence_contract.confidence_label,
            confidence_reasons=list(confidence_contract.confidence_reasons),
            confidence_risk_flags=list(confidence_contract.confidence_risk_flags),
            comparable_count=result.comparables_used,
            price_m2_uf=_clp_to_uf(adjusted_estimated_clp, uf_to_clp) / built_area_m2,
            status="ok",
            warnings=_dedupe(warnings),
            comparable_quality_level=result.comparable_quality_level,
            comparable_quality_flags=list(result.comparable_quality_flags),
            comparable_quality_metrics=dict(result.comparable_quality_metrics),
            beta_scope_status=result.beta_scope_status,
            beta_scope_flags=list(result.beta_scope_flags),
            beta_scope_metrics=dict(result.beta_scope_metrics),
            beta_scope_message=result.beta_scope_message,
            surface_adjustment_applied=adjustment.adjustment_applied,
            surface_adjustment_weight=adjustment.adjustment_weight,
            surface_adjustment_reason=adjustment.adjustment_reason,
            comparables=[
                _comparable_dto(score.value, listing, uf_to_clp)
                for score, listing in valuation_run.scored_comparables
            ],
        )


def _comparable_dto(similarity: float, listing: Listing, uf_to_clp: Decimal) -> ComparableDTO:
    return ComparableDTO(
        listing_id=listing.id,
        title=listing.title,
        comuna=listing.comuna,
        price_uf=price_uf_float(listing.price, uf_to_clp),
        price_clp=price_clp_int(listing.price),
        m2=listing.m2,
        built_area_m2=listing.built_area_m2,
        land_area_m2=listing.land_area_m2,
        usable_area_m2=listing.usable_area_m2,
        similarity=round(similarity, 4),
        url=listing.url,
    )


def _clp_to_uf(value: int | float | Decimal, uf_to_clp: Decimal) -> float:
    return round(float(Decimal(str(value)) / uf_to_clp), 2)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _beta_scope_warning_codes(status: str | None) -> list[str]:
    return beta_scope_warning_codes(status)
