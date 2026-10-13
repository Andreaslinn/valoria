"""Radar opportunity use case facade."""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter

from config import get_settings
from config.constants import MIN_COMPARABLES, MIN_UNDERVALUATION, MIN_UNDERVALUATION_LOW_DATA
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
from domain.radar.eligibility import list_initial_radar_candidates
from domain.radar.filters import apply_quality_filters, top_n
from domain.radar.freshness import (
    RadarFreshnessConfig,
)
from domain.radar.price_basis import display_price_uf, radar_price_basis
from domain.radar.scope import parse_allowed_property_types
from domain.valuation.comparables import filter_candidates, valuate
from services.formatting import price_clp_int, price_uf_float
from services.uf_rate import require_real_uf_rate
from services.valuation import ValuationService
from services.listing_analysis import _valuation_input
from services.listing_url_lookup import listing_to_form_data

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
class RadarFilters:
    bedrooms_min: int | None = None
    bedrooms_max: int | None = None
    bathrooms_min: int | None = None
    price_min: float | None = None
    price_max: float | None = None
    comuna: str | None = None
    area_min: float | None = None
    area_max: float | None = None

    def __post_init__(self) -> None:
        for name in ("bedrooms_min", "bedrooms_max"):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise ValueError(f"{name} debe ser mayor o igual a 1")
        if (
            self.bedrooms_min is not None
            and self.bedrooms_max is not None
            and self.bedrooms_min > self.bedrooms_max
        ):
            raise ValueError("bedrooms_min no puede ser mayor que bedrooms_max")

    @property
    def bedrooms_filter_applied(self) -> bool:
        return self.bedrooms_min is not None or self.bedrooms_max is not None


@dataclass(frozen=True)
class RadarFilterDiagnostics:
    bedrooms_filter_applied: bool = False
    bedrooms_min: int | None = None
    bedrooms_max: int | None = None
    excluded_by_bedrooms_count: int = 0


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
    valuation_strategy: str | None = None
    consensus_used: bool = False
    consensus_unavailable_reason: str | None = None
    fallback_engine_used: str | None = None
    price_currency: str | None = None
    price_clp_snapshot: int | None = None
    price_basis_used: str | None = None
    price_data_quality: str | None = None
    price_uf_source: str | None = None
    uf_rate_used: float | None = None
    uf_rate_date: str | None = None
    uf_rate_fetched_at: str | None = None
    uf_rate_source: str | None = None
    uf_rate_cache_hit: bool | None = None
    uf_rate_stale: bool | None = None
    built_area_m2: float | None = None
    usable_area_m2: float | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    parking: int | None = None
    property_type: str | None = None
    source: str | None = None
    external_id: str | None = None
    last_seen_at: str | None = None
    lat: float | None = None
    lon: float | None = None
    geocode_precision: str | None = None
    allowed_property_types: list[str] = field(default_factory=list)
    excluded_by_property_type_count: dict[str, int] = field(default_factory=dict)
    houses_on_hold_count: int = 0
    radar_scope_note: str | None = None
    radar_scope_label: str | None = None
    bedrooms_filter_applied: bool = False
    bedrooms_min: int | None = None
    bedrooms_max: int | None = None
    excluded_by_bedrooms_count: int = 0

    def to_payload(self) -> RadarOpportunityPayload:
        return {
            "listing_id": self.listing_id,
            "title": self.title,
            "comuna": self.comuna,
            "price_uf": self.price_uf,
            "price_clp": self.price_clp,
            "m2": self.m2,
            "built_area_m2": self.built_area_m2,
            "usable_area_m2": self.usable_area_m2,
            "bedrooms": self.bedrooms,
            "bathrooms": self.bathrooms,
            "parking": self.parking,
            "property_type": self.property_type,
            "source": self.source,
            "external_id": self.external_id,
            "last_seen_at": self.last_seen_at,
            "lat": self.lat,
            "lon": self.lon,
            "geocode_precision": self.geocode_precision,
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
            "valuation_strategy": self.valuation_strategy,
            "consensus_used": self.consensus_used,
            "consensus_unavailable_reason": self.consensus_unavailable_reason,
            "fallback_engine_used": self.fallback_engine_used,
            "price_currency": self.price_currency,
            "price_clp_snapshot": self.price_clp_snapshot,
            "price_basis_used": self.price_basis_used,
            "price_data_quality": self.price_data_quality,
            "price_uf_source": self.price_uf_source,
            "uf_rate_used": self.uf_rate_used,
            "uf_rate_date": self.uf_rate_date,
            "uf_rate_fetched_at": self.uf_rate_fetched_at,
            "uf_rate_source": self.uf_rate_source,
            "uf_rate_cache_hit": self.uf_rate_cache_hit,
            "uf_rate_stale": self.uf_rate_stale,
            "allowed_property_types": list(self.allowed_property_types),
            "excluded_by_property_type_count": dict(self.excluded_by_property_type_count),
            "houses_on_hold_count": self.houses_on_hold_count,
            "radar_scope_note": self.radar_scope_note,
            "radar_scope_label": self.radar_scope_label,
            "bedrooms_filter_applied": self.bedrooms_filter_applied,
            "bedrooms_min": self.bedrooms_min,
            "bedrooms_max": self.bedrooms_max,
            "excluded_by_bedrooms_count": self.excluded_by_bedrooms_count,
        }


class RadarService:
    def __init__(
        self,
        *,
        listing_repo: ListingRepository,
        uf_service: UFService,
        allowed_property_types: Sequence[str] | None = None,
        freshness_config: RadarFreshnessConfig | None = None,
        valuation_service: ValuationService | None = None,
    ) -> None:
        self._listing_repo = listing_repo
        self._uf_service = uf_service
        self._valuation_service = valuation_service or ValuationService(listing_repo=listing_repo, uf_service=uf_service, final_price_policy="canonical_only")
        settings = get_settings()
        configured_types = (
            allowed_property_types
            if allowed_property_types is not None
            else settings.radar_allowed_property_types
        )
        self._allowed_property_types = parse_allowed_property_types(configured_types)
        self._freshness_config = freshness_config or RadarFreshnessConfig(
            require_fresh_listings=settings.radar_require_fresh_listings,
            max_listing_staleness_days=settings.radar_max_listing_staleness_days,
            exclude_refresh_failed=settings.radar_exclude_refresh_failed,
            exclude_removed_or_unavailable=settings.radar_exclude_removed_or_unavailable,
        )

    async def opportunities(
        self,
        *,
        limit: int = 20,
        filters: RadarFilters | None = None,
    ) -> list[OpportunityDTO]:
        total_start = perf_counter()
        filters = filters or RadarFilters()

        uf_start = perf_counter()
        uf_info = await require_real_uf_rate(self._uf_service)
        uf_to_clp = uf_info.rate
        uf_ms = _elapsed_ms(uf_start)

        listings_start = perf_counter()
        listings = await self._listing_repo.list_active()
        listings_ms = _elapsed_ms(listings_start)

        eligibility = list_initial_radar_candidates(
            listings,
            allowed_property_types=self._allowed_property_types,
            freshness_config=self._freshness_config,
            now=datetime.now(UTC),
        )
        scope = eligibility.scope
        eligibility_diagnostics = eligibility.diagnostics
        scoped_listings, filter_diagnostics = _apply_radar_filters(eligibility.candidates, filters)

        detection_start = perf_counter()
        result = detect_opportunities(
            scoped_listings,
            uf_to_clp,
            comparable_universe=listings,
        )
        detection_ms = _elapsed_ms(detection_start)

        filtering_start = perf_counter()
        filtered = apply_quality_filters(result.opportunities, min_confidence=0.0)
        filtering_ms = _elapsed_ms(filtering_start)

        dto_start = perf_counter()
        opportunities: list[OpportunityDTO] = []
        for o in top_n(filtered, limit):
            # Detection is only a bounded preselection. Every displayed estimate
            # comes from the actual Tasar service, never the screening value.
            valuation_input, missing = _valuation_input(listing_to_form_data(o.listing))
            if missing or valuation_input is None:
                continue
            try:
                valuation = await self._valuation_service.valuate_property(
                    valuation_input, valuation_strategy="consensus_v1",
                )
            except (InsufficientDataError, ValidationError, ValueError):
                _log.info("radar_canonical_valuation_unavailable listing_id=%s", o.listing.id)
                continue
            estimated_uf = valuation.estimated_price_uf
            listed_price_uf = display_price_uf(o.listing, uf_to_clp)
            discount = calculate_discount_pct(estimated_uf, listed_price_uf)
            low_data = result.low_data_by_property_type.get(_property_type(o.listing), result.low_data_mode)
            threshold = MIN_UNDERVALUATION_LOW_DATA if low_data else MIN_UNDERVALUATION
            if discount is None or discount < threshold * 100:
                continue
            warnings = list(valuation.warnings)
            if low_data:
                warnings.append("low_data_mode")
            safety = assess_radar_safety(
                beta_scope_status=valuation.beta_scope_status,
                beta_scope_flags=valuation.beta_scope_flags,
                comparable_quality_level=valuation.comparable_quality_level,
                comparable_quality_flags=valuation.comparable_quality_flags,
                warnings=warnings,
            )
            if not safety.show:
                continue
            basis = radar_price_basis(o.listing)
            opportunities.append(
                OpportunityDTO(
                    listing_id=o.listing.id,
                    title=o.listing.title,
                    comuna=o.listing.comuna,
                    price_uf=listed_price_uf,
                    price_clp=price_clp_int(o.listing.price),
                    m2=float(_effective_area_m2(o.listing) or 0),
                    built_area_m2=_float_or_none(o.listing.built_area_m2),
                    usable_area_m2=_float_or_none(o.listing.usable_area_m2),
                    bedrooms=o.listing.bedrooms,
                    bathrooms=o.listing.bathrooms,
                    parking=o.listing.parking,
                    property_type=_property_type(o.listing),
                    source=o.listing.source,
                    external_id=o.listing.external_id,
                    last_seen_at=(
                        (o.listing.last_seen_at.replace(tzinfo=UTC) if o.listing.last_seen_at.tzinfo is None else o.listing.last_seen_at).isoformat()
                        if o.listing.last_seen_at is not None else None
                    ),
                    lat=o.listing.coordinates.lat if o.listing.coordinates is not None else None,
                    lon=o.listing.coordinates.lon if o.listing.coordinates is not None else None,
                    geocode_precision=o.listing.geocode_precision,
                    estimated_price_uf=estimated_uf,
                    discount_pct=discount,
                    score=round((discount / 100) * (valuation.confidence_score or 0), 4),
                    confidence=valuation.confidence,
                    confidence_score=valuation.confidence_score,
                    confidence_label=valuation.confidence_label,
                    confidence_reasons=list(valuation.confidence_reasons),
                    confidence_risk_flags=list(valuation.confidence_risk_flags),
                    comparables_used=valuation.comparable_count,
                    url=o.listing.url,
                    warnings=_dedupe(warnings),
                    radar_verdict=safety.verdict,
                    radar_verdict_message=safety.message,
                    risk_flags=list(safety.risk_flags),
                    comparable_quality_level=valuation.comparable_quality_level,
                    comparable_quality_flags=list(valuation.comparable_quality_flags),
                    beta_scope_status=valuation.beta_scope_status,
                    beta_scope_message=valuation.beta_scope_message,
                    beta_scope_flags=list(valuation.beta_scope_flags),
                    estimated_value_uf=estimated_uf,
                    estimated_value_clp=valuation.estimated_price_clp,
                    valuation_strategy=valuation.valuation_strategy,
                    consensus_used=valuation.consensus_used,
                    consensus_unavailable_reason=valuation.consensus_unavailable_reason,
                    fallback_engine_used=valuation.fallback_engine_used,
                    price_currency=o.price_currency or basis.price_currency,
                    price_clp_snapshot=int(o.price_clp_snapshot or basis.price_clp_snapshot),
                    price_basis_used=o.price_basis_used or basis.price_basis_used,
                    price_data_quality=o.price_data_quality or basis.price_data_quality,
                    price_uf_source=o.listing.price_uf_source,
                    uf_rate_used=float(uf_to_clp),
                    uf_rate_date=uf_info.rate_date.isoformat() if uf_info.rate_date else None,
                    uf_rate_fetched_at=uf_info.fetched_at.isoformat() if uf_info.fetched_at else None,
                    uf_rate_source=uf_info.source,
                    uf_rate_cache_hit=uf_info.cache_hit,
                    uf_rate_stale=uf_info.is_stale,
                    allowed_property_types=list(scope.allowed_property_types),
                    excluded_by_property_type_count=dict(scope.excluded_by_property_type_count),
                    houses_on_hold_count=scope.houses_on_hold_count,
                    radar_scope_note=scope.radar_scope_note,
                    radar_scope_label=scope.radar_scope_label,
                    bedrooms_filter_applied=filter_diagnostics.bedrooms_filter_applied,
                    bedrooms_min=filter_diagnostics.bedrooms_min,
                    bedrooms_max=filter_diagnostics.bedrooms_max,
                    excluded_by_bedrooms_count=filter_diagnostics.excluded_by_bedrooms_count,
                )
            )
        opportunities.sort(key=lambda item: item.score, reverse=True)
        dto_ms = _elapsed_ms(dto_start)
        _log.info(
            "radar_opportunities_timing limit=%s listings_loaded=%s "
            "allowed_property_types=%s excluded_by_property_type_count=%s "
            "houses_on_hold_count=%s bedrooms_filter_applied=%s "
            "bedrooms_min=%s bedrooms_max=%s excluded_by_bedrooms_count=%s "
            "freshness_required=%s freshness_max_staleness_days=%s "
            "scoped_listings=%s freshness_included=%s "
            "freshness_excluded_missing_url=%s freshness_excluded_stale=%s "
            "freshness_excluded_removed_or_unavailable=%s "
            "freshness_excluded_refresh_failed=%s "
            "freshness_excluded_missing_freshness=%s "
            "candidates_sent_to_detector=%s "
            "listings_analyzed=%s opportunities_detected=%s "
            "opportunities_filtered=%s opportunities_returned=%s "
            "total_candidates=%s processed_candidates=%s "
            "skipped_invalid_area=%s skipped_validation_error=%s "
            "uf_ms=%.1f listings_ms=%.1f detection_ms=%.1f "
            "filtering_ms=%.1f dto_ms=%.1f total_ms=%.1f",
            limit,
            len(listings),
            ",".join(scope.allowed_property_types),
            scope.excluded_by_property_type_count,
            scope.houses_on_hold_count,
            filter_diagnostics.bedrooms_filter_applied,
            filter_diagnostics.bedrooms_min,
            filter_diagnostics.bedrooms_max,
            filter_diagnostics.excluded_by_bedrooms_count,
            self._freshness_config.require_fresh_listings,
            self._freshness_config.max_listing_staleness_days,
            len(scope.included),
            eligibility_diagnostics.fresh_candidates_count,
            eligibility_diagnostics.freshness_excluded_missing_url_count,
            eligibility_diagnostics.excluded_stale_count,
            eligibility_diagnostics.excluded_removed_count,
            eligibility_diagnostics.freshness_excluded_refresh_failed_count,
            eligibility_diagnostics.freshness_excluded_missing_freshness_count,
            len(scoped_listings),
            result.total_listings_analyzed,
            len(result.opportunities),
            len(filtered),
            len(opportunities),
            result.total_candidates,
            result.processed_candidates,
            result.skipped_invalid_area,
            result.skipped_validation_error,
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


def _apply_radar_filters(
    listings: Sequence[Listing],
    filters: RadarFilters,
) -> tuple[list[Listing], RadarFilterDiagnostics]:
    if not filters.bedrooms_filter_applied:
        return list(listings), RadarFilterDiagnostics()

    included: list[Listing] = []
    excluded_by_bedrooms = 0
    for listing in listings:
        bedrooms = listing.bedrooms
        if bedrooms is None:
            excluded_by_bedrooms += 1
            continue
        if filters.bedrooms_min is not None and bedrooms < filters.bedrooms_min:
            excluded_by_bedrooms += 1
            continue
        if filters.bedrooms_max is not None and bedrooms > filters.bedrooms_max:
            excluded_by_bedrooms += 1
            continue
        included.append(listing)

    return included, RadarFilterDiagnostics(
        bedrooms_filter_applied=True,
        bedrooms_min=filters.bedrooms_min,
        bedrooms_max=filters.bedrooms_max,
        excluded_by_bedrooms_count=excluded_by_bedrooms,
    )


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
    from core.normalization.property_consistency import property_type_conflict
    if property_type_conflict(listing):
        return False
    area = _effective_area_m2(listing)
    return (
        listing.is_active
        and bool(listing.comuna)
        and area is not None
        and area > 0
        and listing.price.clp > 0
    )


def _is_valid_comparable_input(listing: Listing) -> bool:
    return _is_valid_target(listing)


def _same_listing(a: Listing, b: Listing) -> bool:
    from core.normalization.publication_identity import same_publication
    return same_publication(a, b)


def _same_property_type(a: Listing, b: Listing) -> bool:
    return _property_type(a) == _property_type(b)


def _effective_area_m2(listing: Listing) -> float | None:
    return listing.built_area_m2 or listing.usable_area_m2 or listing.m2


def _float_or_none(value: float | Decimal | None) -> float | None:
    return float(value) if value is not None else None


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
