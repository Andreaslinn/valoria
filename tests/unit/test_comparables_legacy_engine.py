from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import pytest

from core.entities.listing import Listing
from core.exceptions import InsufficientDataError
from core.ports.listing_repo import ListingRepository
from core.ports.uf_service import UFService
from domain.valuation.engines.contracts import EngineContext, EngineRequest, EngineStatus
from domain.valuation.engines.legacy_comparables import ComparablesLegacyEngine
from services.valuation import ValuationInput, ValuationService
from tests.unit.factories import make_listing, make_property

UF = Decimal("39000")


class FakeListingRepository(ListingRepository):
    def __init__(self, listings: Sequence[Listing]) -> None:
        self._listings = list(listings)

    async def save(self, listing: Listing) -> Listing:
        return listing

    async def find_by_id(self, listing_id: int) -> Listing | None:
        return None

    async def list(self, *, limit: int = 100, offset: int = 0, comuna: str | None = None, status: str | None = None):
        return self._listings[offset : offset + limit]

    async def list_active(self, *, limit: int | None = None):
        rows = [listing for listing in self._listings if listing.status == "active"]
        return rows[:limit] if limit is not None else rows

    async def find_by_fingerprint(self, fingerprint: str) -> Listing | None:
        return None

    async def find_by_source_external_id(self, source: str, external_id: str) -> Listing | None:
        return None

    async def find_active_in_comuna(self, comuna_slug: str, *, property_type: str | None = None):
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
        return UF


async def _service_result(data: ValuationInput, listings: list[Listing]):
    service = ValuationService(listing_repo=FakeListingRepository(listings), uf_service=FakeUFService())
    return await service.valuate_property(data)


def _engine_result(target, candidates, *, published_price_provided: bool = False, canonical: bool | None = None):
    return ComparablesLegacyEngine().valuate(
        EngineRequest(
            published_price_provided=published_price_provided,
            canonical_price_enabled=canonical,
        ),
        EngineContext(target=target, candidates=candidates, uf_to_clp=UF),
    )


@pytest.mark.parametrize(
    ("data", "target", "listings"),
    [
        (
            ValuationInput(comuna="nunoa", property_type="apartment", m2=75, built_area_m2=75, dormitorios=3, banos=2, estacionamientos=1),
            make_property(property_type="apartment", m2=75, built_area_m2=75, coords=None, geocode_precision=None),
            [make_listing(fingerprint=f"apt-{idx}", property_type="apartment", m2=75, price_clp=180_000_000) for idx in range(5)],
        ),
        (
            ValuationInput(comuna="nunoa", property_type="house", m2=140, built_area_m2=140, land_area_m2=400, dormitorios=3, banos=2, estacionamientos=1),
            make_property(property_type="house", m2=140, built_area_m2=140, land_area_m2=400, usable_area_m2=None, coords=None, geocode_precision=None),
            [
                make_listing(
                    fingerprint=f"house-{idx}",
                    property_type="house",
                    m2=140,
                    built_area_m2=140,
                    land_area_m2=400,
                    price_clp=700_000_000,
                )
                for idx in range(5)
            ],
        ),
        (
            ValuationInput(comuna="nunoa", property_type="house", m2=140, built_area_m2=140, dormitorios=3, banos=2, estacionamientos=1),
            make_property(property_type="house", m2=140, built_area_m2=140, land_area_m2=None, usable_area_m2=None, coords=None, geocode_precision=None),
            [
                make_listing(
                    fingerprint=f"house-no-land-{idx}",
                    property_type="house",
                    m2=140,
                    built_area_m2=140,
                    land_area_m2=None,
                    price_clp=650_000_000,
                )
                for idx in range(5)
            ],
        ),
    ],
)
async def test_comparables_legacy_matches_service_outputs(data, target, listings) -> None:
    service = await _service_result(data, listings)
    engine = _engine_result(target, listings)

    assert engine.status == EngineStatus.OK
    assert int(engine.estimated_price_clp or 0) == service.estimated_price_clp
    assert int(engine.range_low_clp or 0) == service.price_range_low_clp
    assert int(engine.range_high_clp or 0) == service.price_range_high_clp
    assert engine.confidence == service.confidence_score
    assert engine.comparables_used == service.comparable_count
    assert list(engine.warnings) == service.warnings
    assert [item.fingerprint for item in engine.selected_comparables] == [listing.fingerprint for listing in listings]
    assert engine.diagnostics["comparable_quality_level"] == service.comparable_quality_level
    assert engine.diagnostics["beta_scope_status"] == service.beta_scope_status
    assert engine.diagnostics["surface_adjustment"]["applied"] == service.surface_adjustment_applied


def test_comparables_legacy_reports_insufficient_data() -> None:
    target = make_property(m2=75)
    result = _engine_result(target, [make_listing(fingerprint=f"few-{idx}") for idx in range(4)])

    assert result.status == EngineStatus.INSUFFICIENT_DATA
    assert result.error_code == "insufficient_data"


def test_comparables_legacy_canonical_mode_passthrough() -> None:
    target = make_property(m2=75)
    listings = [
        make_listing(
            fingerprint=f"uf-{idx}",
            price_clp=200_000_000,
            price_currency="UF",
            price_uf=Decimal("4000"),
            price_uf_source="scraped",
            price_uf_confidence="high",
        )
        for idx in range(5)
    ]

    result = _engine_result(target, listings, canonical=True)

    assert result.status == EngineStatus.OK
    assert result.diagnostics["reliability_metrics"]["canonical_price_enabled"] is True
    assert result.diagnostics["reliability_metrics"]["canonical_price_mode"] == "canonical"


async def test_service_still_raises_legacy_insufficient_data() -> None:
    service = ValuationService(
        listing_repo=FakeListingRepository([make_listing(fingerprint=f"few-{idx}") for idx in range(4)]),
        uf_service=FakeUFService(),
    )

    with pytest.raises(InsufficientDataError):
        await service.valuate_property(ValuationInput(comuna="nunoa", property_type="apartment", m2=75))
