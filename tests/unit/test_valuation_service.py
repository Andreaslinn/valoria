"""Tests de ValuationService."""
from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import pytest

from api.v1.valuations import ValuationResponse
from core.entities.listing import Listing
from core.exceptions import InsufficientDataError, ValidationError
from core.ports.listing_repo import ListingRepository
from core.ports.uf_service import UFService
from domain.valuation import comparables
from domain.valuation.engines.contracts import (
    EngineContext,
    EngineRequest,
    EngineResult,
    EngineStatus,
)
from domain.valuation.engines.registry import EngineRegistry
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


class _StubEngine:
    def __init__(self, name: str, estimate: int) -> None:
        self.name = name
        self.version = f"{name}_test_v1"
        self._estimate = Decimal(estimate)

    def valuate(self, request: EngineRequest, context: EngineContext) -> EngineResult:
        return EngineResult(
            engine_name=self.name,
            engine_version=self.version,
            status=EngineStatus.OK,
            estimated_price_clp=self._estimate,
            estimated_price_uf=self._estimate / Decimal("39000"),
            range_low_clp=self._estimate - Decimal("10000000"),
            range_high_clp=self._estimate + Decimal("10000000"),
            confidence=0.8,
            comparables_used=8,
        )


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
    monkeypatch.setenv("VALORIA_EXPERIMENTAL_ENGINE_LAB_ENABLED", "false")
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
    assert result.valuation_verdict is None
    assert result.engine_breakdown == []
    assert result.consensus_audit is None
    assert result.weight_audit == []


async def test_experimental_engine_lab_metadata_is_optional_and_does_not_change_estimate(monkeypatch) -> None:
    monkeypatch.setenv("VALORIA_USE_CONSENSUS", "false")
    monkeypatch.setenv("VALORIA_EXPERIMENTAL_ENGINE_LAB_ENABLED", "true")
    listings = [
        make_listing(
            fingerprint=f"lab-{idx}",
            price_clp=180_000_000 + idx * 1_000_000,
            price_uf=4600 + idx * 20,
            price_currency="UF",
        )
        for idx in range(10)
    ]
    service = ValuationService(
        listing_repo=FakeListingRepository(listings),
        uf_service=FakeUFService(),
    )

    result = await service.valuate_property(
        ValuationInput(comuna="nunoa", property_type="apartment", m2=75)
    )

    assert result.estimated_price_clp == 184_500_000
    assert result.valuation_verdict is not None
    assert result.valuation_verdict["source"] in {
        "consensus_experimental",
        "current_valuation",
    }
    assert result.engine_breakdown
    assert {
        "comparables_canonical_outliers",
        "microzone_geo_v1",
        "hedonic_baseline_v1",
    } <= {item["engine_name"] for item in result.engine_breakdown}
    assert result.consensus_audit is not None
    assert isinstance(result.weight_audit, list)


async def test_experimental_engine_lab_failure_does_not_break_valuation(monkeypatch) -> None:
    monkeypatch.setenv("VALORIA_USE_CONSENSUS", "false")
    monkeypatch.setenv("VALORIA_EXPERIMENTAL_ENGINE_LAB_ENABLED", "true")

    def fail_lab(*args, **kwargs):
        raise RuntimeError("lab unavailable")

    monkeypatch.setattr("services.valuation.run_experimental_engine_lab", fail_lab)
    listings = [
        make_listing(fingerprint=f"lab-fail-{idx}", price_clp=180_000_000)
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
    assert result.valuation_verdict is None
    assert result.engine_breakdown == []


async def test_consensus_flag_alone_preserves_current_strategy(
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
    assert result.valuation_strategy == "current"
    assert result.consensus_used is False
    assert result.consensus is None
    assert result.engine_results == []


async def test_consensus_strategy_uses_two_valid_families(monkeypatch) -> None:
    monkeypatch.setenv("VALORIA_USE_CONSENSUS", "true")
    listings = [
        make_listing(fingerprint=f"consensus-{idx}", price_clp=180_000_000)
        for idx in range(8)
    ]
    registry = EngineRegistry()
    registry.register(_StubEngine("comparables_canonical_outliers", 190_000_000))
    registry.register(_StubEngine("hedonic_baseline_v1", 186_000_000))
    service = ValuationService(
        listing_repo=FakeListingRepository(listings),
        uf_service=FakeUFService(),
        engine_registry=registry,
    )

    result = await service.valuate_property(
        ValuationInput(comuna="nunoa", property_type="apartment", m2=75),
        valuation_strategy="consensus_v1",
    )

    assert result.valuation_strategy == "consensus_v1"
    assert result.consensus_used is True
    assert result.selected_engine_names == ["valoria_consensus_v1"]
    assert result.consensus is not None
    assert result.consensus.valid_engine_count == 2
    assert result.consensus.engine_family_count == 2
    assert result.consensus.estimate_clp == result.estimated_price_clp
    assert result.consensus_method == "valoria_consensus_v1_min_two_families"


async def test_consensus_response_with_list_verdict_explanation_is_serializable(monkeypatch) -> None:
    monkeypatch.setenv("VALORIA_USE_CONSENSUS", "true")
    listings = [
        make_listing(fingerprint=f"consensus-serializable-{idx}", price_clp=180_000_000)
        for idx in range(8)
    ]
    registry = EngineRegistry()
    registry.register(_StubEngine("comparables_canonical_outliers", 190_000_000))
    registry.register(_StubEngine("hedonic_baseline_v1", 186_000_000))
    service = ValuationService(
        listing_repo=FakeListingRepository(listings),
        uf_service=FakeUFService(),
        engine_registry=registry,
    )

    result = await service.valuate_property(
        ValuationInput(comuna="nunoa", property_type="apartment", m2=75),
        valuation_strategy="consensus_v1",
    )

    assert isinstance(result.valuation_verdict["explanation"], list)
    response = ValuationResponse.model_validate(result, from_attributes=True)
    payload = response.model_dump(mode="json")

    assert payload["valuation_strategy"] == "consensus_v1"
    assert payload["consensus_used"] is True
    assert isinstance(payload["valuation_verdict"]["explanation"], list)
    assert payload["estimated_price_uf"] is not None


async def test_consensus_strategy_with_one_family_keeps_current_fallback(monkeypatch) -> None:
    monkeypatch.setenv("VALORIA_USE_CONSENSUS", "true")
    listings = [
        make_listing(fingerprint=f"legacy-fallback-{idx}", price_clp=180_000_000)
        for idx in range(6)
    ]
    registry = EngineRegistry()
    registry.register(_StubEngine("comparables_canonical_outliers", 190_000_000))
    service = ValuationService(
        listing_repo=FakeListingRepository(listings),
        uf_service=FakeUFService(),
        engine_registry=registry,
    )

    result = await service.valuate_property(
        ValuationInput(comuna="nunoa", property_type="apartment", m2=75),
        valuation_strategy="consensus_v1",
    )

    assert result.estimated_price_clp == 180_000_000
    assert result.valuation_strategy == "current_engine_fallback"
    assert result.consensus_used is False
    assert result.consensus_unavailable_reason == "insufficient_distinct_engine_families"
    assert result.fallback_engine_used == "current_valuation"
    assert result.consensus is not None
    assert result.consensus.valid_engine_count == 1


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


def _quality_v2_listings(prices: list[int], *, comuna: str = "nunoa", property_type: str = "apartment") -> list[Listing]:
    return [
        make_listing(
            fingerprint=f"qv2-{comuna}-{property_type}-{idx}",
            comuna=comuna,
            property_type=property_type,
            m2=75,
            built_area_m2=75,
            price_clp=price,
        )
        for idx, price in enumerate(prices)
    ]


def _enable_quality_v2(monkeypatch, mode: str) -> None:
    monkeypatch.setenv("VALORIA_USE_CONSENSUS", "false")
    monkeypatch.setenv("VALUATION_QUALITY_V2_APPLY_MODE", mode)
    monkeypatch.setenv("VALUATION_QUALITY_V2_ALLOWED_PROPERTY_TYPES", "apartment")
    monkeypatch.setenv("VALUATION_QUALITY_V2_BLOCKED_COMUNAS", "estacion central,la reina,macul")
    monkeypatch.setenv("VALUATION_QUALITY_V2_MAX_POOL_DISPERSION", "75")
    monkeypatch.setenv("VALUATION_QUALITY_V2_MAX_DELTA_VS_BASELINE_PCT", "0.25")
    monkeypatch.setenv("VALUATION_QUALITY_V2_MIN_VALID_COMPARABLES", "5")


async def test_quality_v2_off_preserves_baseline(monkeypatch) -> None:
    _enable_quality_v2(monkeypatch, "off")
    listings = _quality_v2_listings([100_000_000, 100_000_000, 100_000_000, 130_000_000, 130_000_000])
    service = ValuationService(listing_repo=FakeListingRepository(listings), uf_service=FakeUFService())

    result = await service.valuate_property(ValuationInput(comuna="nunoa", property_type="apartment", m2=75))

    assert result.estimated_price_clp == 112_000_000
    assert result.engine_results == []
    assert result.selected_engine_names == []


async def test_quality_v2_shadow_does_not_change_final_estimate(monkeypatch) -> None:
    _enable_quality_v2(monkeypatch, "shadow")
    listings = _quality_v2_listings([100_000_000, 100_000_000, 100_000_000, 130_000_000, 130_000_000])
    service = ValuationService(listing_repo=FakeListingRepository(listings), uf_service=FakeUFService())

    result = await service.valuate_property(ValuationInput(comuna="nunoa", property_type="apartment", m2=75))

    assert result.estimated_price_clp == 112_000_000
    assert len(result.engine_results) == 1
    shadow = result.engine_results[0]
    assert shadow.engine_name == "comparables_quality_v2"
    assert shadow.role == "shadow"
    assert shadow.estimate_clp == 100_000_000
    assert shadow.selected_for_final is False


async def test_quality_v2_guarded_uses_challenger_when_guardrails_pass(monkeypatch) -> None:
    _enable_quality_v2(monkeypatch, "guarded")
    listings = _quality_v2_listings([100_000_000, 100_000_000, 100_000_000, 130_000_000, 130_000_000])
    service = ValuationService(listing_repo=FakeListingRepository(listings), uf_service=FakeUFService())

    result = await service.valuate_property(ValuationInput(comuna="nunoa", property_type="apartment", m2=75))

    assert result.estimated_price_clp == 100_000_000
    assert result.selected_engine_names == ["comparables_quality_v2"]
    assert result.engine_results[0].selected_for_final is True


async def test_quality_v2_guarded_falls_back_for_bad_comuna(monkeypatch) -> None:
    _enable_quality_v2(monkeypatch, "guarded")
    listings = _quality_v2_listings(
        [100_000_000, 100_000_000, 100_000_000, 130_000_000, 130_000_000],
        comuna="macul",
    )
    service = ValuationService(listing_repo=FakeListingRepository(listings), uf_service=FakeUFService())

    result = await service.valuate_property(ValuationInput(comuna="macul", property_type="apartment", m2=75))

    assert result.estimated_price_clp == 112_000_000
    assert result.selected_engine_names == []
    assert result.engine_results[0].safe_error_message == "CQ v2 esta deshabilitado para esta comuna por guardrail."


async def test_quality_v2_guarded_falls_back_with_few_valid_comparables(monkeypatch) -> None:
    _enable_quality_v2(monkeypatch, "guarded")
    monkeypatch.setenv("VALUATION_QUALITY_V2_MIN_VALID_COMPARABLES", "6")
    listings = _quality_v2_listings([100_000_000, 100_000_000, 100_000_000, 130_000_000, 130_000_000])
    service = ValuationService(listing_repo=FakeListingRepository(listings), uf_service=FakeUFService())

    result = await service.valuate_property(ValuationInput(comuna="nunoa", property_type="apartment", m2=75))

    assert result.estimated_price_clp == 112_000_000
    assert result.engine_results[0].warnings == ["insufficient_valid_comparables"]


async def test_quality_v2_guarded_falls_back_when_pool_dispersion_is_high(monkeypatch) -> None:
    _enable_quality_v2(monkeypatch, "guarded")
    listings = _quality_v2_listings([50_000_000, 50_000_000, 100_000_000, 150_000_000, 150_000_000])
    service = ValuationService(listing_repo=FakeListingRepository(listings), uf_service=FakeUFService())

    result = await service.valuate_property(ValuationInput(comuna="nunoa", property_type="apartment", m2=75))

    assert result.estimated_price_clp == 100_000_000
    assert result.engine_results[0].warnings == ["pool_dispersion_too_high"]


async def test_quality_v2_guarded_falls_back_when_delta_exceeds_threshold(monkeypatch) -> None:
    _enable_quality_v2(monkeypatch, "guarded")
    monkeypatch.setenv("VALUATION_QUALITY_V2_MAX_POOL_DISPERSION", "500")
    listings = _quality_v2_listings([100_000_000, 100_000_000, 100_000_000, 300_000_000, 300_000_000])
    service = ValuationService(listing_repo=FakeListingRepository(listings), uf_service=FakeUFService())

    result = await service.valuate_property(ValuationInput(comuna="nunoa", property_type="apartment", m2=75))

    assert result.estimated_price_clp == 180_000_000
    assert result.engine_results[0].warnings == ["delta_vs_baseline_too_high"]


async def test_quality_v2_house_not_allowed_by_default(monkeypatch) -> None:
    _enable_quality_v2(monkeypatch, "guarded")
    listings = _quality_v2_listings(
        [500_000_000, 500_000_000, 500_000_000, 650_000_000, 650_000_000],
        property_type="house",
    )
    service = ValuationService(listing_repo=FakeListingRepository(listings), uf_service=FakeUFService())

    result = await service.valuate_property(
        ValuationInput(comuna="nunoa", property_type="house", m2=75, built_area_m2=75)
    )

    assert result.estimated_price_clp == 560_000_000
    assert result.engine_results[0].warnings == ["property_type_not_allowed"]


async def test_quality_v2_does_not_require_subject_actual_price(monkeypatch) -> None:
    _enable_quality_v2(monkeypatch, "guarded")
    listings = _quality_v2_listings([100_000_000, 100_000_000, 100_000_000, 130_000_000, 130_000_000])
    service = ValuationService(listing_repo=FakeListingRepository(listings), uf_service=FakeUFService())

    result = await service.valuate_property(
        ValuationInput(
            comuna="nunoa",
            property_type="apartment",
            m2=75,
            precio_publicado_uf=None,
            precio_publicado_clp=None,
        )
    )

    assert result.estimated_price_clp == 100_000_000
    assert "published_price_not_provided" in result.warnings


def make_listing_target_property():
    from tests.unit.factories import make_property

    return make_property(m2=75, property_type="apartment")
