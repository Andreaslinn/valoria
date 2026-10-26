"""Unit coverage for RadarService AVM enrichment."""
from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

import services.radar as radar_module
from config import get_settings
from core.entities.listing import Listing
from core.entities.opportunity import Opportunity, RadarResult, ValuationResult
from core.ports.uf_service import UFRateInfo
from core.value_objects.price import Price
from core.value_objects.score import Score
from domain.radar.freshness import RadarFreshnessConfig
from domain.radar.price_basis import display_price_uf
from services.radar import (
    RadarFilters,
    RadarService,
    calculate_discount_pct,
    enrich_listing_with_avm,
)
from tests.unit.factories import make_listing

UF = Decimal("39000")
MARKET_PRICE = 180_000_000
NOW = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _legacy_freshness_for_existing_radar_service_tests(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RADAR_REQUIRE_FRESH_LISTINGS", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _market_listings(n: int) -> list:
    return [
        make_listing(fingerprint=f"market-{idx}", price_clp=MARKET_PRICE)
        for idx in range(n)
    ]


def _without_valid_area(fingerprint: str) -> Listing:
    listing = make_listing(fingerprint=fingerprint)
    listing.m2 = None
    listing.built_area_m2 = None
    listing.usable_area_m2 = None
    return listing


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


def test_nataniel_clp_price_uses_current_uf_for_display() -> None:
    listing = make_listing(
        fingerprint="nataniel",
        title="Departamento en Nataniel Cox",
        price_clp=70_000_000,
        price_currency="CLP",
        price_uf_source="scraped",
        m2=46,
        bedrooms=2,
        bathrooms=1,
        parking=0,
    )

    assert round(display_price_uf(listing, Decimal("41931.34")), 1) == 1669.4


def _fresh_listing(fingerprint: str, *, last_seen_at: datetime) -> Listing:
    listing = make_listing(fingerprint=fingerprint)
    listing.url = f"https://example.test/{fingerprint}"
    listing.last_seen_at = last_seen_at
    return listing


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
    assert opportunity.bedrooms == cheap.bedrooms
    assert opportunity.bathrooms == cheap.bathrooms
    assert opportunity.parking == cheap.parking
    assert opportunity.property_type == "apartment"
    assert opportunity.source == cheap.source
    assert opportunity.external_id == cheap.external_id
    assert opportunity.lat == cheap.coordinates.lat
    assert opportunity.lon == cheap.coordinates.lon
    assert opportunity.geocode_precision == cheap.geocode_precision
    assert opportunity.uf_rate_used == float(UF)
    assert opportunity.uf_rate_source == "test"
    assert opportunity.uf_rate_cache_hit is False
    assert opportunity.uf_rate_stale is False
    payload = opportunity.to_payload()
    assert payload["lat"] == cheap.coordinates.lat
    assert payload["lon"] == cheap.coordinates.lon
    assert payload["geocode_precision"] == cheap.geocode_precision


@pytest.mark.asyncio
async def test_radar_service_skips_invalid_area_and_returns_valid_opportunities() -> None:
    cheap = make_listing(fingerprint="cheap", price_clp=int(MARKET_PRICE * 0.86))
    service = RadarService(
        listing_repo=_FakeListingRepo(
            [cheap, _without_valid_area("invalid-area"), *_market_listings(14)]
        ),
        uf_service=_FakeUFService(),
    )

    opportunities = await service.opportunities(limit=5)

    assert any(item.title == "Depto cheap" for item in opportunities)
    assert all(item.title != "Depto invalid-area" for item in opportunities)


@pytest.mark.asyncio
async def test_radar_service_all_invalid_areas_returns_empty_list() -> None:
    service = RadarService(
        listing_repo=_FakeListingRepo(
            [_without_valid_area(f"invalid-{idx}") for idx in range(12)]
        ),
        uf_service=_FakeUFService(),
    )

    assert await service.opportunities(limit=5) == []


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
    assert opportunity.price_uf_source == "scraped"


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
        allowed_property_types=("apartment", "house"),
    )

    opportunities = await service.opportunities(limit=5)

    opportunity = next(item for item in opportunities if item.title == "Depto cheap-house")
    assert "low_data_mode" in opportunity.warnings
    assert opportunity.radar_verdict == "revisar"


@pytest.mark.asyncio
async def test_radar_service_filters_houses_before_detector(monkeypatch) -> None:
    apartment = make_listing(fingerprint="apt", property_type="apartment")
    house = make_listing(fingerprint="house", property_type="house")
    captured_property_types: list[str] = []

    def fake_detect(listings, *args, **kwargs):
        captured_property_types.extend(listing.property_type for listing in listings)
        return RadarResult(
            opportunities=[],
            total_listings_analyzed=len(listings),
            low_data_mode=False,
            low_data_by_property_type={"apartment": False},
        )

    monkeypatch.setattr(radar_module, "detect_opportunities", fake_detect)
    service = RadarService(
        listing_repo=_FakeListingRepo([apartment, house]),
        uf_service=_FakeUFService(),
    )

    assert await service.opportunities(limit=5) == []
    assert captured_property_types == ["apartment"]


@pytest.mark.asyncio
async def test_radar_service_sends_only_initially_eligible_candidates_to_detector(monkeypatch) -> None:
    ready = make_listing(fingerprint="ready", price_currency="CLP", price_uf=None)
    missing_price = make_listing(fingerprint="missing-price", price_currency="UF", price_uf=None)
    missing_area = _without_valid_area("missing-area")
    captured_fingerprints: list[str] = []

    def fake_detect(listings, *args, **kwargs):
        captured_fingerprints.extend(listing.fingerprint for listing in listings)
        return RadarResult(
            opportunities=[],
            total_listings_analyzed=len(listings),
            low_data_mode=False,
            low_data_by_property_type={"apartment": False},
        )

    monkeypatch.setattr(radar_module, "detect_opportunities", fake_detect)
    service = RadarService(
        listing_repo=_FakeListingRepo([ready, missing_price, missing_area]),
        uf_service=_FakeUFService(),
    )

    assert await service.opportunities(limit=5) == []
    assert captured_fingerprints == ["ready"]


@pytest.mark.asyncio
async def test_radar_service_without_bedrooms_filter_keeps_detector_input(monkeypatch) -> None:
    studio = make_listing(fingerprint="studio", bedrooms=0)
    one_bed = make_listing(fingerprint="one-bed", bedrooms=1)
    unknown = make_listing(fingerprint="unknown")
    unknown.bedrooms = None
    captured_fingerprints: list[str] = []

    def fake_detect(listings, *args, **kwargs):
        captured_fingerprints.extend(listing.fingerprint for listing in listings)
        return RadarResult(
            opportunities=[],
            total_listings_analyzed=len(listings),
            low_data_mode=False,
            low_data_by_property_type={"apartment": False},
        )

    monkeypatch.setattr(radar_module, "detect_opportunities", fake_detect)
    service = RadarService(
        listing_repo=_FakeListingRepo([studio, one_bed, unknown]),
        uf_service=_FakeUFService(),
    )

    assert await service.opportunities(limit=5) == []
    assert captured_fingerprints == ["studio", "one-bed", "unknown"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("bedrooms_min", "expected_fingerprints"),
    [
        (1, ["one-bed", "two-bed", "three-bed", "house-three"]),
        (2, ["two-bed", "three-bed", "house-three"]),
        (3, ["three-bed", "house-three"]),
    ],
)
async def test_radar_service_applies_bedrooms_filter_before_detector(
    monkeypatch,
    bedrooms_min: int,
    expected_fingerprints: list[str],
) -> None:
    studio = make_listing(fingerprint="studio", bedrooms=0)
    one_bed = make_listing(fingerprint="one-bed", bedrooms=1)
    two_bed = make_listing(fingerprint="two-bed", bedrooms=2)
    three_bed = make_listing(fingerprint="three-bed", bedrooms=3)
    unknown = make_listing(fingerprint="unknown")
    unknown.bedrooms = None
    house_three = make_listing(fingerprint="house-three", bedrooms=3, property_type="house")
    captured_fingerprints: list[str] = []

    def fake_detect(listings, *args, **kwargs):
        captured_fingerprints.extend(listing.fingerprint for listing in listings)
        return RadarResult(
            opportunities=[],
            total_listings_analyzed=len(listings),
            low_data_mode=False,
            low_data_by_property_type={"apartment": False},
        )

    monkeypatch.setattr(radar_module, "detect_opportunities", fake_detect)
    service = RadarService(
        listing_repo=_FakeListingRepo([studio, one_bed, two_bed, three_bed, unknown, house_three]),
        uf_service=_FakeUFService(),
        allowed_property_types=("apartment", "house"),
    )

    assert await service.opportunities(limit=5, filters=RadarFilters(bedrooms_min=bedrooms_min)) == []
    assert captured_fingerprints == expected_fingerprints


@pytest.mark.asyncio
async def test_radar_service_bedrooms_filter_respects_apartment_scope(monkeypatch) -> None:
    apartment = make_listing(fingerprint="apt-three", bedrooms=3, property_type="apartment")
    house = make_listing(fingerprint="house-three", bedrooms=3, property_type="house")
    captured_fingerprints: list[str] = []

    def fake_detect(listings, *args, **kwargs):
        captured_fingerprints.extend(listing.fingerprint for listing in listings)
        return RadarResult(
            opportunities=[],
            total_listings_analyzed=len(listings),
            low_data_mode=False,
            low_data_by_property_type={"apartment": False},
        )

    monkeypatch.setattr(radar_module, "detect_opportunities", fake_detect)
    service = RadarService(
        listing_repo=_FakeListingRepo([apartment, house]),
        uf_service=_FakeUFService(),
    )

    assert await service.opportunities(limit=5, filters=RadarFilters(bedrooms_min=3)) == []
    assert captured_fingerprints == ["apt-three"]


@pytest.mark.asyncio
async def test_radar_service_freshness_on_filters_stale_before_detector(monkeypatch) -> None:
    current = datetime.now(UTC)
    fresh = _fresh_listing("fresh", last_seen_at=current - timedelta(days=2))
    stale = _fresh_listing("stale", last_seen_at=current - timedelta(days=30))
    captured_fingerprints: list[str] = []
    captured_comparable_fingerprints: list[str] = []

    def fake_detect(listings, *args, **kwargs):
        captured_fingerprints.extend(listing.fingerprint for listing in listings)
        captured_comparable_fingerprints.extend(
            listing.fingerprint for listing in kwargs["comparable_universe"]
        )
        return RadarResult(
            opportunities=[],
            total_listings_analyzed=len(listings),
            low_data_mode=False,
            low_data_by_property_type={"apartment": False},
        )

    monkeypatch.setattr(radar_module, "detect_opportunities", fake_detect)
    service = RadarService(
        listing_repo=_FakeListingRepo([fresh, stale]),
        uf_service=_FakeUFService(),
        freshness_config=RadarFreshnessConfig(
            require_fresh_listings=True,
            max_listing_staleness_days=7,
        ),
    )

    assert await service.opportunities(limit=5) == []
    assert captured_fingerprints == ["fresh"]
    assert captured_comparable_fingerprints == ["fresh", "stale"]


@pytest.mark.asyncio
async def test_radar_service_freshness_off_preserves_legacy_detector_input(monkeypatch) -> None:
    current = datetime.now(UTC)
    fresh = _fresh_listing("fresh", last_seen_at=current - timedelta(days=2))
    stale = _fresh_listing("stale", last_seen_at=current - timedelta(days=30))
    missing_url = _fresh_listing("missing-url", last_seen_at=current - timedelta(days=30))
    missing_url.url = None
    captured_fingerprints: list[str] = []

    def fake_detect(listings, *args, **kwargs):
        captured_fingerprints.extend(listing.fingerprint for listing in listings)
        return RadarResult(
            opportunities=[],
            total_listings_analyzed=len(listings),
            low_data_mode=False,
            low_data_by_property_type={"apartment": False},
        )

    monkeypatch.setattr(radar_module, "detect_opportunities", fake_detect)
    service = RadarService(
        listing_repo=_FakeListingRepo([fresh, stale, missing_url]),
        uf_service=_FakeUFService(),
        freshness_config=RadarFreshnessConfig(require_fresh_listings=False),
    )

    assert await service.opportunities(limit=5) == []
    assert captured_fingerprints == ["fresh", "stale", "missing-url"]


def test_radar_filters_reject_invalid_bedrooms_values() -> None:
    with pytest.raises(ValueError):
        RadarFilters(bedrooms_min=0)
    with pytest.raises(ValueError):
        RadarFilters(bedrooms_min=3, bedrooms_max=2)


@pytest.mark.asyncio
async def test_radar_service_scope_metadata_counts_houses_on_hold(monkeypatch) -> None:
    listing = make_listing(fingerprint="fake-scope", property_type="apartment", price_clp=100_000_000)
    house = make_listing(fingerprint="fake-house", property_type="house", price_clp=100_000_000)
    valuation = _valuation_result(
        beta_scope_status="beta_supported",
        beta_scope_flags=[],
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
        listing_repo=_FakeListingRepo([listing, house]),
        uf_service=_FakeUFService(),
        valuation_service=_CanonicalValuationStub(valuation),
    )

    result = (await service.opportunities(limit=5))[0]

    assert result.allowed_property_types == ["apartment"]
    assert result.excluded_by_property_type_count == {"house": 1}
    assert result.houses_on_hold_count == 1
    assert result.radar_scope_label == "Departamentos"
    assert result.radar_scope_note == "Radar beta: por ahora analiza solo departamentos."


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
        valuation_service=_CanonicalValuationStub(valuation),
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
        valuation_service=_CanonicalValuationStub(valuation),
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
    assert "total_candidates=15" in caplog.text
    assert "processed_candidates=15" in caplog.text
    assert "skipped_invalid_area=0" in caplog.text
    assert "skipped_validation_error=0" in caplog.text
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


class _CanonicalValuationStub:
    def __init__(self, result):
        self.result = result
    async def valuate_property(self, data, *, valuation_strategy):
        from types import SimpleNamespace
        v = self.result
        return SimpleNamespace(estimated_price_uf=float(v.estimated_price.clp / UF),
            estimated_price_clp=int(v.estimated_price.clp), confidence_score=v.confidence.value,
            confidence_risk_flags=list(v.reliability_warnings), confidence="medium", confidence_label="medium", confidence_reasons=[], comparable_count=v.comparables_used,
            warnings=list(v.reliability_warnings), beta_scope_status=v.beta_scope_status,
            beta_scope_flags=v.beta_scope_flags, beta_scope_message=v.beta_scope_message,
            comparable_quality_level=v.comparable_quality_level,
            comparable_quality_flags=v.comparable_quality_flags, valuation_strategy=valuation_strategy,
            consensus_used=True, consensus_unavailable_reason=None, fallback_engine_used=None)
