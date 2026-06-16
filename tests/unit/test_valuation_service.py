"""Tests de ValuationService."""
from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import pytest

from core.entities.listing import Listing
from core.exceptions import InsufficientDataError, ValidationError
from core.ports.listing_repo import ListingRepository
from core.ports.uf_service import UFService
from domain.valuation import comparables
from services.valuation import ValuationInput, ValuationService
from tests.unit.factories import make_listing


class FakeListingRepository(ListingRepository):
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
        return rows[offset: offset + limit]

    async def list_active(self, *, limit: int | None = None) -> Sequence[Listing]:
        rows = [listing for listing in self._listings if listing.status == "active"]
        return rows[:limit] if limit is not None else rows

    async def find_by_fingerprint(self, fingerprint: str) -> Listing | None:
        return next((listing for listing in self._listings if listing.fingerprint == fingerprint), None)

    async def find_by_source_external_id(self, source: str, external_id: str) -> Listing | None:
        return next(
            (
                listing
                for listing in self._listings
                if listing.source == source and listing.external_id == external_id
            ),
            None,
        )

    async def find_active_in_comuna(
        self,
        comuna_slug: str,
        *,
        property_type: str | None = None,
    ) -> Sequence[Listing]:
        rows = [
            listing
            for listing in self._listings
            if listing.status == "active" and listing.comuna == comuna_slug
        ]
        if property_type is not None:
            rows = [listing for listing in rows if listing.property_type == property_type]
        return rows

    async def count_active(self) -> int:
        return len([listing for listing in self._listings if listing.status == "active"])


class FakeUFService(UFService):
    async def get_current_rate(self) -> Decimal:
        return Decimal("39000")


async def test_unknown_property_type_adds_warning_and_low_data_mode() -> None:
    listings = [
        make_listing(fingerprint=f"u{i}", property_type="unknown", m2=75)
        for i in range(5)
    ]
    service = ValuationService(
        listing_repo=FakeListingRepository(listings),
        uf_service=FakeUFService(),
    )

    result = await service.valuate_property(
        ValuationInput(
            comuna="nunoa",
            property_type="unknown",
            m2=75,
            built_area_m2=75,
            land_area_m2=None,
            usable_area_m2=None,
            dormitorios=3,
            banos=2,
            estacionamientos=1,
        )
    )

    assert result.comparable_count == 5
    assert result.confidence == result.confidence_label
    assert result.confidence_score is not None
    assert result.confidence_label in {"low", "medium", "high"}
    assert "low_comparable_count" in result.confidence_risk_flags
    assert "unknown_property_type" in result.warnings
    assert "low_data_mode" in result.warnings
    assert "low_comparable_count" in result.warnings
    assert result.beta_scope_status in {"weak_data", "exploratory"}
    assert result.beta_scope_message


async def test_missing_all_area_fields_returns_validation_error_not_type_error() -> None:
    service = ValuationService(
        listing_repo=FakeListingRepository([]),
        uf_service=FakeUFService(),
    )

    with pytest.raises(ValidationError, match="m2"):
        await service.valuate_property(
            ValuationInput(
                comuna="nunoa",
                property_type="apartment",
                m2=None,
                built_area_m2=None,
                land_area_m2=None,
                usable_area_m2=None,
            )
        )


async def test_apartment_valuation_uses_only_apartment_comparables() -> None:
    apartment_listings = [
        make_listing(fingerprint=f"apt-{idx}", property_type="apartment", m2=75, price_clp=180_000_000)
        for idx in range(5)
    ]
    house_listings = [
        make_listing(
            fingerprint=f"house-{idx}",
            property_type="house",
            m2=75,
            built_area_m2=75,
            land_area_m2=300,
            price_clp=900_000_000,
        )
        for idx in range(5)
    ]
    service = ValuationService(
        listing_repo=FakeListingRepository([*apartment_listings, *house_listings]),
        uf_service=FakeUFService(),
    )

    result = await service.valuate_property(
        ValuationInput(
            comuna="nunoa",
            property_type="apartment",
            m2=75,
            built_area_m2=75,
            usable_area_m2=75,
            dormitorios=3,
            banos=2,
            estacionamientos=1,
        )
    )

    assert result.estimated_price_clp == 180_000_000
    assert result.comparable_count == 5
    assert {dto.title for dto in result.comparables} == {f"Depto apt-{idx}" for idx in range(5)}


async def test_house_valuation_uses_only_house_comparables() -> None:
    apartment_listings = [
        make_listing(fingerprint=f"apt-{idx}", property_type="apartment", m2=140, price_clp=180_000_000)
        for idx in range(5)
    ]
    house_listings = [
        make_listing(
            fingerprint=f"house-{idx}",
            property_type="house",
            m2=140,
            built_area_m2=140,
            land_area_m2=400,
            price_clp=700_000_000,
        )
        for idx in range(5)
    ]
    service = ValuationService(
        listing_repo=FakeListingRepository([*apartment_listings, *house_listings]),
        uf_service=FakeUFService(),
    )

    result = await service.valuate_property(
        ValuationInput(
            comuna="nunoa",
            property_type="house",
            m2=140,
            built_area_m2=140,
            land_area_m2=400,
            dormitorios=3,
            banos=2,
            estacionamientos=1,
        )
    )

    assert result.estimated_price_clp == 700_000_000
    assert result.comparable_count == 5
    assert {dto.title for dto in result.comparables} == {f"Depto house-{idx}" for idx in range(5)}


async def test_valuation_does_not_backfill_missing_apartment_comparables_with_houses() -> None:
    listings = [
        make_listing(fingerprint=f"apt-{idx}", property_type="apartment", m2=75, price_clp=180_000_000)
        for idx in range(4)
    ] + [
        make_listing(
            fingerprint=f"house-{idx}",
            property_type="house",
            m2=75,
            built_area_m2=75,
            land_area_m2=300,
            price_clp=180_000_000,
        )
        for idx in range(10)
    ]
    service = ValuationService(
        listing_repo=FakeListingRepository(listings),
        uf_service=FakeUFService(),
    )

    with pytest.raises(InsufficientDataError):
        await service.valuate_property(
            ValuationInput(
                comuna="nunoa",
                property_type="apartment",
                m2=75,
                built_area_m2=75,
                usable_area_m2=75,
            )
        )


async def test_unknown_valuation_does_not_mix_with_apartments() -> None:
    service = ValuationService(
        listing_repo=FakeListingRepository([
            make_listing(fingerprint=f"apt-{idx}", property_type="apartment", m2=75)
            for idx in range(10)
        ]),
        uf_service=FakeUFService(),
    )

    with pytest.raises(InsufficientDataError):
        await service.valuate_property(
            ValuationInput(
                comuna="nunoa",
                property_type="unknown",
                m2=75,
                built_area_m2=75,
            )
        )


async def test_service_uses_single_valuation_run_for_result_and_dto(monkeypatch) -> None:
    calls = {"filter": 0, "score": 0}
    original_filter = comparables.filter_candidates
    original_score = comparables.score_and_rank
    listings = [
        make_listing(fingerprint=f"single-run-{idx}", m2=75 + idx)
        for idx in range(6)
    ]

    def counting_filter(target, candidates):
        calls["filter"] += 1
        return original_filter(target, candidates)

    def counting_score(target, candidates):
        calls["score"] += 1
        return original_score(target, candidates)

    monkeypatch.setattr(comparables, "filter_candidates", counting_filter)
    monkeypatch.setattr(comparables, "score_and_rank", counting_score)
    service = ValuationService(
        listing_repo=FakeListingRepository(listings),
        uf_service=FakeUFService(),
    )

    result = await service.valuate_property(
        ValuationInput(
            comuna="nunoa",
            property_type="apartment",
            m2=75,
            built_area_m2=75,
            land_area_m2=None,
            usable_area_m2=None,
            dormitorios=3,
            banos=2,
            estacionamientos=1,
        )
    )

    assert calls == {"filter": 1, "score": 1}
    assert result.comparable_count == len(result.comparables)
    assert [dto.title for dto in result.comparables] == [
        listing.title for _, listing in original_score(
            make_listing_target_property(),
            original_filter(make_listing_target_property(), listings),
        )
    ][: result.comparable_count]


async def test_valuation_returns_surface_adjustment_audit_fields() -> None:
    listings = [
        make_listing(fingerprint=f"adjust-{idx}", m2=75, price_clp=150_000_000)
        for idx in range(10)
    ]
    service = ValuationService(
        listing_repo=FakeListingRepository(listings),
        uf_service=FakeUFService(),
    )

    result = await service.valuate_property(
        ValuationInput(
            comuna="nunoa",
            property_type="apartment",
            m2=75,
            built_area_m2=75,
            dormitorios=3,
            banos=2,
            estacionamientos=1,
        )
    )

    assert result.base_estimated_price_clp is not None
    assert result.estimated_price_clp is not None
    assert result.surface_adjustment_applied in {True, False}
    assert 0.0 <= result.surface_adjustment_weight <= 0.2
    assert result.surface_adjustment_reason
    assert result.beta_scope_status in {
        "exploratory",
        "beta_supported",
        "strong_sample",
        "weak_data",
    }
    assert isinstance(result.beta_scope_metrics, dict)


async def test_consensus_flag_disabled_preserves_legacy_flow(monkeypatch) -> None:
    monkeypatch.setenv("VALORIA_USE_CONSENSUS", "false")
    listings = [
        make_listing(fingerprint=f"legacy-{idx}", price_clp=180_000_000)
        for idx in range(6)
    ]
    service = ValuationService(
        listing_repo=FakeListingRepository(listings),
        uf_service=FakeUFService(),
    )

    result = await service.valuate_property(
        ValuationInput(comuna="nunoa", property_type="apartment", m2=75)
    )

    assert result.estimated_price_clp == 180_000_000
    assert result.comparable_count == 6
    assert result.consensus is None
    assert result.engine_results == []
    assert result.selected_engine_names == []
    assert result.consensus_method is None


async def test_consensus_uses_real_canonical_outliers_and_preserves_core_fields(
    monkeypatch,
) -> None:
    monkeypatch.setenv("VALORIA_USE_CONSENSUS", "true")
    listings = [
        make_listing(
            fingerprint=f"canonical-{idx}",
            price_clp=180_000_000 + idx * 500_000,
            price_currency="CLP",
        )
        for idx in range(8)
    ]
    service = ValuationService(
        listing_repo=FakeListingRepository(listings),
        uf_service=FakeUFService(),
    )

    result = await service.valuate_property(
        ValuationInput(
            comuna="nunoa",
            property_type="apartment",
            m2=75,
            built_area_m2=75,
            dormitorios=3,
            banos=2,
            estacionamientos=1,
        )
    )

    assert result.status == "ok"
    assert result.estimated_price_clp is not None
    assert result.price_range_low_clp is not None
    assert result.price_range_high_clp is not None
    assert result.confidence_score is not None
    assert result.comparable_count == len(result.comparables)
    assert result.selected_engine_names == ["comparables_canonical_outliers"]
    assert result.consensus is not None
    assert result.consensus.estimate_clp == result.estimated_price_clp
    assert result.consensus_method == "favorite_first_with_legacy_fallback_v1"
    assert {item.engine_name for item in result.engine_results} == {
        "comparables_canonical_outliers",
        "comparables_legacy",
        "comparables_canonical",
    }


async def test_consensus_falls_back_to_real_legacy_engine(monkeypatch) -> None:
    monkeypatch.setenv("VALORIA_USE_CONSENSUS", "true")
    listings = [
        make_listing(fingerprint=f"legacy-fallback-{idx}", price_clp=180_000_000)
        for idx in range(6)
    ]
    service = ValuationService(
        listing_repo=FakeListingRepository(listings),
        uf_service=FakeUFService(),
    )

    result = await service.valuate_property(
        ValuationInput(comuna="nunoa", property_type="apartment", m2=75)
    )

    assert result.estimated_price_clp == 180_000_000
    assert result.selected_engine_names == ["comparables_legacy"]
    legacy = next(
        item for item in result.engine_results if item.engine_name == "comparables_legacy"
    )
    assert legacy.role == "fallback"
    assert legacy.selected_for_final is True


async def test_consensus_all_engines_insufficient_keeps_controlled_error(
    monkeypatch,
) -> None:
    monkeypatch.setenv("VALORIA_USE_CONSENSUS", "true")
    service = ValuationService(
        listing_repo=FakeListingRepository(
            [make_listing(fingerprint=f"few-{idx}") for idx in range(4)]
        ),
        uf_service=FakeUFService(),
    )

    with pytest.raises(InsufficientDataError, match="Solo 4 comparables"):
        await service.valuate_property(
            ValuationInput(comuna="nunoa", property_type="apartment", m2=75)
        )


def make_listing_target_property():
    from tests.unit.factories import make_property

    return make_property(m2=75, property_type="apartment")
