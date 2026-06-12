"""Radar opportunity use case facade."""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from time import perf_counter

from config.constants import MIN_COMPARABLES
from core.assessment.beta_status import beta_scope_warning_codes
from core.assessment.confidence import build_confidence_contract
from core.assessment.contracts import RadarOpportunityPayload
from core.entities.listing import Listing, Property
from core.entities.opportunity import Opportunity, ValuationResult
from core.exceptions import InsufficientDataError, ValidationError
from core.normalization.property_type import normalize_property_type as _property_type
from core.ports.listing_repo import ListingRepository
from core.ports.uf_service import UFService
from domain.radar.beta_safety import assess_radar_safety
from domain.radar.detector import detect_opportunities
from domain.radar.filters import apply_quality_filters, top_n
from domain.radar.price_basis import display_price_uf, radar_price_basis
from domain.valuation.comparables import filter_candidates, valuate
from services.formatting import price_clp_int, price_uf_float
from services.uf_rate import require_real_uf_rate

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RadarAvmEnrichment:
    estimated_value_uf: float | None
    estimated_value_clp: int | None
    confidence_score: float | None
    confidence_label: str
    confidence_reasons: list[str]
    confidence_risk_flags: list[str]
    discount_pct: float | None


@dataclass(frozen=True)
class OpportunityDTO:
    listing_id: int | None
    title: str
    comuna: str
    price_uf: float
    price_clp: int
    m2: float
    estimated_price_uf: float
    discount_pct: float
    score: float
    confidence: str
    confidence_score: float | None
    confidence_label: str
    confidence_reasons: list[str]
    confidence_risk_flags: list[str]
    comparables_used: int
    url: str | None
    warnings: list[str]
    radar_verdict: str
    radar_verdict_message: str
    risk_flags: list[str]
    comparable_quality_level: str | None = None
    comparable_quality_flags: list[str] = field(default_factory=list)
    beta_scope_status: str | None = None
    beta_scope_message: str | None = None
    beta_scope_flags: list[str] = field(default_factory=list)
    estimated_value_uf: float | None = None
    estimated_value_clp: int | None = None
    price_currency: str | None = None
    price_clp_snapshot: int | None = None
    price_basis_used: str | None = None
    price_data_quality: str | None = None

    def to_payload(self) -> RadarOpportunityPayload:
        return {
            "listing_id": self.listing_id,
            "title": self.title,
            "comuna": self.comuna,
            "price_uf": self.price_uf,
            "price_clp": self.price_clp,
            "m2": self.m2,
            "estimated_price_uf": self.estimated_price_uf,
            "discount_pct": self.discount_pct,
            "score": self.score,
            "confidence": self.confidence,
            "confidence_score": self.confidence_score,
            "confidence_label": self.confidence_label,
            "confidence_reasons": list(self.confidence_reasons),
            "confidence_risk_flags": list(self.confidence_risk_flags),
            "comparables_used": self.comparables_used,
            "url": self.url,
            "warnings": list(self.warnings),
            "radar_verdict": self.radar_verdict,
            "radar_verdict_message": self.radar_verdict_message,
            "risk_flags": list(self.risk_flags),
            "comparable_quality_level": self.comparable_quality_level,
            "comparable_quality_flags": list(self.comparable_quality_flags),
            "beta_scope_status": self.beta_scope_status,
            "beta_scope_message": self.beta_scope_message,
            "beta_scope_flags": list(self.beta_scope_flags),
            "estimated_value_uf": self.estimated_value_uf,
            "estimated_value_clp": self.estimated_value_clp,
            "price_currency": self.price_currency,
            "price_clp_snapshot": self.price_clp_snapshot,
            "price_basis_used": self.price_basis_used,
            "price_data_quality": self.price_data_quality,
        }


class RadarService:
    def __init__(
        self,
        *,
        listing_repo: ListingRepository,
        uf_service: UFService,
    ) -> None:
        self._listing_repo = listing_repo
        self._uf_service = uf_service

    async def opportunities(self, *, limit: int = 20) -> list[OpportunityDTO]:
        total_start = perf_counter()

        uf_start = perf_counter()
        uf_info = await require_real_uf_rate(self._uf_service)
        uf_to_clp = uf_info.rate
        uf_ms = _elapsed_ms(uf_start)

        listings_start = perf_counter()
        listings = await self._listing_repo.list_active()
        listings_ms = _elapsed_ms(listings_start)

        detection_start = perf_counter()
        result = detect_opportunities(listings, uf_to_clp)
        detection_ms = _elapsed_ms(detection_start)

        filtering_start = perf_counter()
        filtered = apply_quality_filters(result.opportunities, min_confidence=0.0)
        filtering_ms = _elapsed_ms(filtering_start)

        dto_start = perf_counter()
        opportunities: list[OpportunityDTO] = []
        for o in top_n(filtered, limit):
            warnings: list[str] = []
            if result.low_data_by_property_type.get(_property_type(o.listing), result.low_data_mode):
                warnings.append("low_data_mode")
            if o.valuation_result is not None:
                warnings.extend(o.valuation_result.reliability_warnings)
                warnings.extend(o.valuation_result.comparable_quality_flags)
                warnings.extend(_beta_scope_warning_codes(o.valuation_result.beta_scope_status))
            safety = _safety_for_opportunity(o, warnings)
            if not safety.show:
                continue
            basis = radar_price_basis(o.listing)
            listed_price_uf = display_price_uf(o.listing, uf_to_clp)
            avm = _enrichment_from_opportunity(o, listings, uf_to_clp)
            opportunity_confidence = build_confidence_contract(
                score=o.confidence,
                base_score=(
                    o.valuation_result.base_confidence
                    if o.valuation_result is not None
                    else None
                ),
                reliability_warnings=(
                    o.valuation_result.reliability_warnings
                    if o.valuation_result is not None
                    else ()
                ),
            )
            opportunities.append(
                OpportunityDTO(
                    listing_id=o.listing.id,
                    title=o.listing.title,
                    comuna=o.listing.comuna,
                    price_uf=listed_price_uf,
                    price_clp=price_clp_int(o.listing.price),
                    m2=float(o.listing.m2 or 0),
                    estimated_price_uf=price_uf_float(o.market_price, uf_to_clp),
                    discount_pct=round(o.discount_pct * 100, 2),
                    score=round(o.ranking_score, 4),
                    confidence=opportunity_confidence.legacy_confidence,
                    confidence_score=opportunity_confidence.confidence_score,
                    confidence_label=opportunity_confidence.confidence_label,
                    confidence_reasons=list(opportunity_confidence.confidence_reasons),
                    confidence_risk_flags=list(opportunity_confidence.confidence_risk_flags),
                    comparables_used=o.comparables_used,
                    url=o.listing.url,
                    warnings=_dedupe(warnings),
                    radar_verdict=safety.verdict,
                    radar_verdict_message=safety.message,
                    risk_flags=list(safety.risk_flags),
                    comparable_quality_level=(
                        o.valuation_result.comparable_quality_level
                        if o.valuation_result is not None
                        else None
                    ),
                    comparable_quality_flags=(
                        list(o.valuation_result.comparable_quality_flags)
                        if o.valuation_result is not None
                        else []
                    ),
                    beta_scope_status=(
                        o.valuation_result.beta_scope_status
                        if o.valuation_result is not None
                        else None
                    ),
                    beta_scope_message=(
                        o.valuation_result.beta_scope_message
                        if o.valuation_result is not None
                        else None
                    ),
                    beta_scope_flags=(
                        list(o.valuation_result.beta_scope_flags)
                        if o.valuation_result is not None
                        else []
                    ),
                    estimated_value_uf=avm.estimated_value_uf,
                    estimated_value_clp=avm.estimated_value_clp,
                    price_currency=o.price_currency or basis.price_currency,
                    price_clp_snapshot=int(o.price_clp_snapshot or basis.price_clp_snapshot),
                    price_basis_used=o.price_basis_used or basis.price_basis_used,
                    price_data_quality=o.price_data_quality or basis.price_data_quality,
                )
            )
        dto_ms = _elapsed_ms(dto_start)
        _log.info(
            "radar_opportunities_timing limit=%s listings_loaded=%s "
            "listings_analyzed=%s opportunities_detected=%s "
            "opportunities_filtered=%s opportunities_returned=%s "
            "uf_ms=%.1f listings_ms=%.1f detection_ms=%.1f "
            "filtering_ms=%.1f dto_ms=%.1f total_ms=%.1f",
            limit,
            len(listings),
            result.total_listings_analyzed,
            len(result.opportunities),
            len(filtered),
            len(opportunities),
            uf_ms,
            listings_ms,
            detection_ms,
            filtering_ms,
            dto_ms,
            _elapsed_ms(total_start),
        )
        return opportunities


def _elapsed_ms(start: float) -> float:
    return (perf_counter() - start) * 1000


def _enrichment_from_opportunity(
    opportunity: Opportunity,
    listings: Sequence[Listing],
    uf_to_clp: Decimal,
) -> RadarAvmEnrichment:
    if opportunity.valuation_result is None:
        return enrich_listing_with_avm(opportunity.listing, listings, uf_to_clp)
    return _enrichment_from_valuation_result(opportunity, opportunity.valuation_result, uf_to_clp)


def _enrichment_from_valuation_result(
    opportunity: Opportunity,
    valuation: ValuationResult,
    uf_to_clp: Decimal,
) -> RadarAvmEnrichment:
    estimated_value_uf = price_uf_float(valuation.estimated_price, uf_to_clp)
    listed_price_uf = display_price_uf(opportunity.listing, uf_to_clp)
    confidence = build_confidence_contract(
        score=valuation.confidence,
        base_score=valuation.base_confidence,
        reliability_warnings=valuation.reliability_warnings,
    )
    return RadarAvmEnrichment(
        estimated_value_uf=estimated_value_uf,
        estimated_value_clp=price_clp_int(valuation.estimated_price),
        confidence_score=confidence.confidence_score,
        confidence_label=confidence.confidence_label,
        confidence_reasons=list(confidence.confidence_reasons),
        confidence_risk_flags=list(confidence.confidence_risk_flags),
        discount_pct=calculate_discount_pct(estimated_value_uf, listed_price_uf),
    )


def calculate_discount_pct(
    estimated_value_uf: float | None,
    listed_price_uf: float | None,
) -> float | None:
    if estimated_value_uf is None or estimated_value_uf == 0:
        return None
    if listed_price_uf is None:
        return None
    return round(((estimated_value_uf - listed_price_uf) / estimated_value_uf) * 100, 2)


def enrich_listing_with_avm(
    target: Listing,
    universe: Sequence[Listing],
    uf_to_clp: Decimal,
) -> RadarAvmEnrichment:
    candidates = [
        listing
        for listing in universe
        if (
            _is_valid_comparable_input(listing)
            and _same_property_type(target, listing)
            and not _same_listing(target, listing)
        )
    ]
    if not _is_valid_target(target):
        return _insufficient_avm()

    target_property = _listing_as_property(target)
    if len(filter_candidates(target_property, candidates)) < MIN_COMPARABLES:
        return _insufficient_avm()

    try:
        valuation = valuate(target_property, candidates, uf_to_clp)
    except (InsufficientDataError, ValidationError):
        return _insufficient_avm()

    estimated_value_uf = price_uf_float(valuation.estimated_price, uf_to_clp)
    listed_price_uf = display_price_uf(target, uf_to_clp)
    confidence = build_confidence_contract(
        score=valuation.confidence,
        base_score=valuation.base_confidence,
        reliability_warnings=valuation.reliability_warnings,
    )
    return RadarAvmEnrichment(
        estimated_value_uf=estimated_value_uf,
        estimated_value_clp=price_clp_int(valuation.estimated_price),
        confidence_score=confidence.confidence_score,
        confidence_label=confidence.confidence_label,
        confidence_reasons=list(confidence.confidence_reasons),
        confidence_risk_flags=list(confidence.confidence_risk_flags),
        discount_pct=calculate_discount_pct(estimated_value_uf, listed_price_uf),
    )


def _insufficient_avm() -> RadarAvmEnrichment:
    return RadarAvmEnrichment(
        estimated_value_uf=None,
        estimated_value_clp=None,
        confidence_score=None,
        confidence_label="insufficient_data",
        confidence_reasons=["insufficient_data"],
        confidence_risk_flags=[],
        discount_pct=None,
    )


def _is_valid_target(listing: Listing) -> bool:
    return (
        listing.is_active
        and bool(listing.comuna)
        and listing.m2 is not None
        and listing.m2 > 0
        and listing.price.clp > 0
    )


def _is_valid_comparable_input(listing: Listing) -> bool:
    return _is_valid_target(listing)


def _same_listing(a: Listing, b: Listing) -> bool:
    if a.id is not None and b.id is not None:
        return a.id == b.id
    return a.fingerprint == b.fingerprint


def _same_property_type(a: Listing, b: Listing) -> bool:
    return _property_type(a) == _property_type(b)


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


def _safety_for_opportunity(o: Opportunity, warnings: list[str]):
    valuation = o.valuation_result
    return assess_radar_safety(
        beta_scope_status=valuation.beta_scope_status if valuation is not None else None,
        beta_scope_flags=valuation.beta_scope_flags if valuation is not None else (),
        comparable_quality_level=valuation.comparable_quality_level if valuation is not None else None,
        comparable_quality_flags=valuation.comparable_quality_flags if valuation is not None else (),
        warnings=warnings,
    )


def _listing_as_property(listing: Listing) -> Property:
    return Property(
        id=listing.property_id,
        comuna=listing.comuna,
        m2=float(listing.m2 or 0),
        property_type=listing.property_type,
        built_area_m2=listing.built_area_m2,
        land_area_m2=listing.land_area_m2,
        usable_area_m2=listing.usable_area_m2,
        bedrooms=listing.bedrooms,
        bathrooms=listing.bathrooms,
        parking=listing.parking,
        coordinates=listing.coordinates,
        geocode_precision=listing.geocode_precision,
        raw_metadata=listing.raw_metadata,
    )
