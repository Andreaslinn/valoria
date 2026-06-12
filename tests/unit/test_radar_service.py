"""Unit coverage for RadarService AVM enrichment."""
from __future__ import annotations

import logging
from collections.abc import Sequence
from decimal import Decimal

import pytest

import services.radar as radar_module
from core.entities.listing import Listing
from core.entities.opportunity import Opportunity, RadarResult, ValuationResult
from core.ports.uf_service import UFRateInfo
from core.value_objects.price import Price
from core.value_objects.score import Score
from services.radar import RadarService, calculate_discount_pct, enrich_listing_with_avm
from tests.unit.factories import make_listing

UF = Decimal("39000")
MARKET_PRICE = 180_000_000


def _market_listings(n: int) -> list:
    return [
        make_listing(fingerprint=f"market-{idx}", price_clp=MARKET_PRICE)
        for idx in range(n)
    ]


def test_discount_pct_under_market() -> None:
    assert calculate_discount_pct(5000.0, 4500.0) == 10.0


def test_discount_pct_over_market_can_be_negative() -> None:
    assert calculate_discount_pct(5000.0, 5250.0) == -5.0


def test_discount_pct_estimated_none() -> None:
    assert calculate_discount_pct(None, 4500.0) is None


def test_discount_pct_estimated_zero() -> None:
    assert calculate_discount_pct(0.0, 4500.0) is None


def test_discount_pct_listed_none() -> None:
    assert calculate_discount_pct(5000.0, None) is None


def test_enrich_listing_with_sufficient_comparables() -> None:
    target = make_listing(fingerprint="target", price_clp=int(MARKET_PRICE * 0.9))
    result = enrich_listing_with_avm(target, [target, *_market_listings(6)], UF)

    assert result.estimated_value_uf is not None
    assert result.estimated_value_clp is not None
    assert result.confidence_score is not None
    assert result.confidence_label in {"low", "medium", "high"}
    assert isinstance(result.confidence_reasons, list)
    assert isinstance(result.confidence_risk_flags, list)
    assert result.discount_pct is not None
    assert result.discount_pct > 0


def test_enrich_listing_without_sufficient_comparables() -> None:
    target = make_listing(fingerprint="target", price_clp=int(MARKET_PRICE * 0.9))
    result = enrich_listing_with_avm(target, [target, *_market_listings(2)], UF)

    assert result.estimated_value_uf is None
    assert result.estimated_value_clp is None
    assert result.confidence_score is None
    assert result.confidence_label == "insufficient_data"
    assert result.confidence_reasons == ["insufficient_data"]
    assert result.discount_pct is None


def test_enrich_listing_does_not_backfill_house_comparables_with_apartments() -> None:
    target = make_listing(
        fingerprint="target-house",
        property_type="house",
        m2=140,
        built_area_m2=140,
        land_area_m2=400,
        price_clp=100_000_000,
    )
    apartments = [
        make_listing(
            fingerprint=f"apt-{idx}",
            property_type="apartment",
            m2=140,
            price_clp=700_000_000,
        )
        for idx in range(10)
    ]

    result = enrich_listing_with_avm(target, [target, *apartments], UF)

    assert result.estimated_value_uf is None
    assert result.estimated_value_clp is None
    assert result.confidence_score is None
    assert result.confidence_label == "insufficient_data"
    assert result.discount_pct is None


def test_enrich_listing_unknown_does_not_mix_with_apartments() -> None:
    target = make_listing(fingerprint="target-unknown", property_type="unknown", m2=75, price_clp=100_000_000)
    apartments = [
        make_listing(fingerprint=f"apt-{idx}", property_type="apartment", m2=75, price_clp=180_000_000)
        for idx in range(10)
    ]

    result = enrich_listing_with_avm(target, [target, *apartments], UF)

    assert result.confidence_label == "insufficient_data"


@pytest.mark.asyncio
async def test_radar_service_opportunity_includes_avm_enrichment() -> None:
    cheap = make_listing(fingerprint="cheap", price_clp=int(MARKET_PRICE * 0.86))
    service = RadarService(
        listing_repo=_FakeListingRepo([cheap, *_market_listings(14)]),
        uf_service=_FakeUFService(),
    )

    opportunities = await service.opportunities(limit=5)

    assert opportunities
    opportunity = next(item for item in opportunities if item.title == "Depto cheap")
    assert opportunity.estimated_value_uf is not None
    assert opportunity.estimated_value_clp is not None
    assert opportunity.confidence_score is not None
    assert opportunity.confidence_label in {"low", "medium", "high"}
    assert opportunity.confidence == opportunity.confidence_label
    assert isinstance(opportunity.confidence_reasons, list)
    assert isinstance(opportunity.confidence_risk_flags, list)
    assert opportunity.beta_scope_status in {
        "exploratory",
        "beta_supported",
        "strong_sample",
        "weak_data",
    }
    assert opportunity.beta_scope_message
    assert opportunity.radar_verdict in {"revisar", "senal_beta", "senal_fuerte"}
    assert isinstance(opportunity.risk_flags, list)
    assert opportunity.price_currency is None
    assert opportunity.price_clp_snapshot == int(MARKET_PRICE * 0.86)
    assert opportunity.price_basis_used == "clp_legacy"
    assert opportunity.price_data_quality == "legacy_unknown_currency"


@pytest.mark.asyncio
async def test_radar_service_payload_exposes_uf_price_provenance() -> None:
    cheap = make_listing(
        fingerprint="uf-cheap",
        price_clp=160_000_000,
        price_currency="UF",
        price_uf=3500,
        price_uf_source="scraped",
    )
    service = RadarService(
        listing_repo=_FakeListingRepo([cheap, *_market_listings(50)]),
        uf_service=_FakeUFService(),
    )

    opportunity = next(item for item in await service.opportunities(limit=5) if item.title == "Depto uf-cheap")

    assert opportunity.price_uf == 3500.0
    assert opportunity.price_clp == 160_000_000
    assert opportunity.price_clp_snapshot == 160_000_000
    assert opportunity.price_currency == "UF"
    assert opportunity.price_basis_used == "uf"
    assert opportunity.price_data_quality == "scraped"


@pytest.mark.asyncio
async def test_radar_service_low_data_warning_is_per_property_type() -> None:
    cheap_apartment = make_listing(fingerprint="cheap", price_clp=int(MARKET_PRICE * 0.86))
    scarce_houses = [
        make_listing(
            fingerprint=f"house-{idx}",
            property_type="house",
            m2=140,
            built_area_m2=140,
            land_area_m2=400,
        )
        for idx in range(4)
    ]
    service = RadarService(
        listing_repo=_FakeListingRepo([cheap_apartment, *_market_listings(50), *scarce_houses]),
        uf_service=_FakeUFService(),
    )

    opportunities = await service.opportunities(limit=5)

    opportunity = next(item for item in opportunities if item.title == "Depto cheap")
    assert "low_data_mode" not in opportunity.warnings


@pytest.mark.asyncio
async def test_radar_service_marks_house_opportunity_low_data_by_type() -> None:
    cheap_house = make_listing(
        fingerprint="cheap-house",
        property_type="house",
        m2=140,
        built_area_m2=140,
        land_area_m2=400,
        price_clp=int(700_000_000 * 0.85),
    )
    house_market = [
        make_listing(
            fingerprint=f"house-{idx}",
            property_type="house",
            m2=140,
            built_area_m2=140,
            land_area_m2=400,
            price_clp=700_000_000,
        )
        for idx in range(14)
    ]
    service = RadarService(
        listing_repo=_FakeListingRepo([cheap_house, *house_market, *_market_listings(50)]),
        uf_service=_FakeUFService(),
    )

    opportunities = await service.opportunities(limit=5)

    opportunity = next(item for item in opportunities if item.title == "Depto cheap-house")
    assert "low_data_mode" in opportunity.warnings
    assert opportunity.radar_verdict == "revisar"


@pytest.mark.asyncio
async def test_radar_service_hides_no_data_opportunities(monkeypatch) -> None:
    listing = make_listing(fingerprint="fake-no-data", price_clp=100_000_000)
    valuation = _valuation_result(
        beta_scope_status="no_data",
        beta_scope_flags=["no_segment_sample"],
        comparable_quality_level="acceptable",
    )
    opportunity = Opportunity(
        listing=listing,
        market_price=valuation.estimated_price,
        discount_pct=0.2,
        confidence=valuation.confidence,
        comparables_used=valuation.comparables_used,
        valuation_result=valuation,
    )

    def fake_detect(*args, **kwargs):
        return RadarResult(
            opportunities=[opportunity],
            total_listings_analyzed=1,
            low_data_mode=False,
            low_data_by_property_type={"apartment": False},
        )

    monkeypatch.setattr(radar_module, "detect_opportunities", fake_detect)
    service = RadarService(
        listing_repo=_FakeListingRepo([listing]),
        uf_service=_FakeUFService(),
    )

    assert await service.opportunities(limit=5) == []


@pytest.mark.asyncio
async def test_radar_service_exposes_quality_and_risk_flags(monkeypatch) -> None:
    listing = make_listing(fingerprint="fake-weak", price_clp=100_000_000)
    valuation = _valuation_result(
        beta_scope_status="beta_supported",
        beta_scope_flags=[],
        comparable_quality_level="weak",
        comparable_quality_flags=["weak_geolocation"],
    )
    opportunity = Opportunity(
        listing=listing,
        market_price=valuation.estimated_price,
        discount_pct=0.2,
        confidence=valuation.confidence,
        comparables_used=valuation.comparables_used,
        valuation_result=valuation,
    )

    def fake_detect(*args, **kwargs):
        return RadarResult(
            opportunities=[opportunity],
            total_listings_analyzed=1,
            low_data_mode=False,
            low_data_by_property_type={"apartment": False},
        )

    monkeypatch.setattr(radar_module, "detect_opportunities", fake_detect)
    service = RadarService(
        listing_repo=_FakeListingRepo([listing]),
        uf_service=_FakeUFService(),
    )

    result = (await service.opportunities(limit=5))[0]

    assert result.radar_verdict == "revisar"
    assert result.comparable_quality_level == "weak"
    assert "weak_geolocation" in result.risk_flags
    assert "weak_geolocation" in result.comparable_quality_flags


@pytest.mark.asyncio
async def test_radar_service_uses_detector_valuation_without_second_enrich(monkeypatch) -> None:
    cheap = make_listing(fingerprint="cheap", price_clp=int(MARKET_PRICE * 0.86))
    service = RadarService(
        listing_repo=_FakeListingRepo([cheap, *_market_listings(14)]),
        uf_service=_FakeUFService(),
    )

    def fail_enrich(*args, **kwargs):
        raise AssertionError("enrich_listing_with_avm should not run for detector opportunities")

    monkeypatch.setattr(radar_module, "enrich_listing_with_avm", fail_enrich)

    opportunities = await service.opportunities(limit=5)

    assert opportunities
    assert all(item.estimated_value_uf is not None for item in opportunities)
    assert all(item.confidence_score is not None for item in opportunities)


@pytest.mark.asyncio
async def test_radar_service_logs_stage_timings(caplog) -> None:
    caplog.set_level(logging.INFO, logger="services.radar")
    cheap = make_listing(fingerprint="cheap", price_clp=int(MARKET_PRICE * 0.86))
    service = RadarService(
        listing_repo=_FakeListingRepo([cheap, *_market_listings(14)]),
        uf_service=_FakeUFService(),
    )

    await service.opportunities(limit=5)

    assert "radar_opportunities_timing" in caplog.text
    assert "listings_loaded=15" in caplog.text
    assert "detection_ms=" in caplog.text
    assert "total_ms=" in caplog.text


class _FakeUFService:
    async def get_current_rate(self) -> Decimal:
        return UF

    async def get_current_rate_info(self) -> UFRateInfo:
        return UFRateInfo(rate=UF, source="test", is_fallback=False)


class _FakeListingRepo:
    def __init__(self, listings: Sequence[Listing]) -> None:
        self._listings = list(listings)

    async def save(self, listing: Listing) -> Listing:
        return listing

    async def find_by_id(self, listing_id: int) -> Listing | None:
        return next((listing for listing in self._listings if listing.id == listing_id), None)

    async def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        comuna: str | None = None,
        status: str | None = None,
    ) -> Sequence[Listing]:
        rows = self._listings
        if comuna is not None:
            rows = [listing for listing in rows if listing.comuna == comuna]
        if status is not None:
            rows = [listing for listing in rows if listing.status == status]
        return rows[offset : offset + limit]

    async def list_active(self, *, limit: int | None = None) -> Sequence[Listing]:
        rows = [listing for listing in self._listings if listing.is_active]
        return rows[:limit] if limit is not None else rows

    async def find_by_fingerprint(self, fingerprint: str) -> Listing | None:
        return next((listing for listing in self._listings if listing.fingerprint == fingerprint), None)

    async def find_active_in_comuna(
        self,
        comuna_slug: str,
        *,
        property_type: str | None = None,
    ) -> Sequence[Listing]:
        rows = [listing for listing in self._listings if listing.is_active and listing.comuna == comuna_slug]
        if property_type is not None:
            rows = [listing for listing in rows if listing.property_type == property_type]
        return rows

    async def count_active(self) -> int:
        return len([listing for listing in self._listings if listing.is_active])


def _valuation_result(
    *,
    beta_scope_status: str,
    beta_scope_flags: list[str],
    comparable_quality_level: str,
    comparable_quality_flags: list[str] | None = None,
) -> ValuationResult:
    return ValuationResult(
        estimated_price=Price(clp=Decimal("180000000")),
        price_range_low=Price(clp=Decimal("160000000")),
        price_range_high=Price(clp=Decimal("200000000")),
        confidence=Score.clamped(0.7),
        comparables_used=10,
        uf_to_clp_rate=UF,
        comparable_quality_level=comparable_quality_level,
        comparable_quality_flags=list(comparable_quality_flags or []),
        comparable_quality_metrics={"n_comparables": 10},
        beta_scope_status=beta_scope_status,
        beta_scope_flags=beta_scope_flags,
        beta_scope_metrics={"segment_sample_count": 10},
        beta_scope_message="scope test",
    )
