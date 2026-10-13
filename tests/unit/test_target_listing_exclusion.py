"""Exact listing exclusion through the URL analysis entry point."""
from dataclasses import replace

import pytest
from fastapi import HTTPException

from services.listing_analysis import analyze_listing_lookup
from services.portfolio_snapshots import _valuation_input as portfolio_input
from services.valuation import ValuationService
from infrastructure.db.models import ListingORM
from tests.unit.factories import make_listing
from tests.unit.test_valuation_service import FakeListingRepository, FakeUFService
from api.v1.valuations import ValuationRequest, valuate


def _pool(independent_count):
    return [replace(make_listing(fingerprint=f"listing-{i}"), id=i, property_id=77)
            for i in range(1, independent_count + 2)]


def _target(listing_id=1):
    return dict(listing_id=listing_id, comuna="nunoa", property_type="apartment",
                m2=75, dormitorios=3, banos=2, estacionamientos=1)


@pytest.mark.parametrize("consensus", [False, True])
async def test_four_real_comparables_plus_target_are_insufficient(monkeypatch, consensus):
    monkeypatch.setenv("VALORIA_USE_CONSENSUS", str(consensus).lower())
    service = ValuationService(listing_repo=FakeListingRepository(_pool(4)), uf_service=FakeUFService())
    result = await analyze_listing_lookup(_target(), valuation_service=service)
    assert result.valuation["estimated_value_uf"] is None
    assert result.price_analysis["verdict"] == "insufficient_data"


@pytest.mark.parametrize("consensus", [False, True])
@pytest.mark.parametrize("count", [5, 8])
@pytest.mark.parametrize("strategy", ["current", "consensus_v1"])
async def test_sufficient_independent_listings_stay_usable(monkeypatch, consensus, count, strategy):
    monkeypatch.setenv("VALORIA_USE_CONSENSUS", str(consensus).lower())
    # Shared property_id is deliberately NOT a reason to exclude other ads.
    service = ValuationService(listing_repo=FakeListingRepository(_pool(count)), uf_service=FakeUFService())
    from services.listing_analysis import _valuation_input
    data, missing = _valuation_input(_target())
    assert not missing
    result = await service.valuate_property(data, valuation_strategy=strategy)
    assert result.estimated_price_uf > 0
    assert result.comparable_count == count
    assert {item.listing_id for item in result.comparables} == set(range(2, count + 2))


async def test_unknown_target_identity_does_not_exclude_candidates():
    service = ValuationService(listing_repo=FakeListingRepository(_pool(4)), uf_service=FakeUFService())
    result = await analyze_listing_lookup(_target(None), valuation_service=service)
    assert result.valuation["estimated_value_uf"] > 0


def test_portfolio_passes_listing_identity():
    listing = ListingORM(id=42, comuna="nunoa", property_type="apartment", m2=75)
    data, error = portfolio_input(listing)
    assert error is None
    assert data.target_listing_id == 42


async def test_tasar_request_preserves_target_identity():
    service = ValuationService(listing_repo=FakeListingRepository(_pool(4)), uf_service=FakeUFService())
    payload = ValuationRequest(comuna="nunoa", property_type="apartment", m2=75,
                               dormitorios=3, banos=2, estacionamientos=1, target_listing_id=1)
    with pytest.raises(HTTPException) as error:
        await valuate(current_user=None, payload=payload, service=service, session=None)
    assert error.value.status_code == 400


@pytest.mark.parametrize("strategy", ["current", "consensus_v1"])
@pytest.mark.parametrize("identity", ["external_id", "url", "portal_slug"])
async def test_duplicate_publication_excluded_before_estimation(strategy, identity):
    pool = _pool(5)
    target = replace(pool[0], id=1130, url="https://www.yapo.cl/venta/depto/123")
    duplicate = replace(pool[-1], id=9999)
    if identity == "external_id":
        duplicate = replace(duplicate, external_id=target.external_id)
    elif identity == "url":
        duplicate = replace(duplicate, url="http://yapo.cl/venta/depto/123/?utm_source=test#photo")
    else:
        target = replace(target, source="portalinmobiliario", url="https://www.portalinmobiliario.com/MLC-123-depto")
        duplicate = replace(duplicate, source="portalinmobiliario", url="https://portalinmobiliario.com/MLC-123-new-slug")
    service = ValuationService(listing_repo=FakeListingRepository([target, *pool[1:-1], duplicate]), uf_service=FakeUFService())
    # Four independent ads plus the duplicate must not satisfy the five-ad gate.
    from services.listing_analysis import _valuation_input
    data, _ = _valuation_input(_target(1130))
    from core.exceptions import InsufficientDataError
    with pytest.raises(InsufficientDataError):
        await service.valuate_property(data, valuation_strategy=strategy)


async def test_withdrawn_target_identity_excludes_active_duplicate():
    pool = _pool(6)
    target = replace(pool[0], id=1130, status="withdrawn")
    duplicate = replace(pool[-1], id=9999, external_id=target.external_id)
    service = ValuationService(listing_repo=FakeListingRepository([target, *pool[1:-1], duplicate]), uf_service=FakeUFService())
    from services.listing_analysis import _valuation_input
    data, _ = _valuation_input(_target(1130))
    result = await service.valuate_property(data, valuation_strategy="consensus_v1")
    assert {item.listing_id for item in result.comparables} == {2, 3, 4, 5, 6}


async def test_external_id_is_namespaced_by_source():
    pool = _pool(5)
    pool[-1] = replace(pool[-1], source="portalinmobiliario", external_id=pool[0].external_id)
    service = ValuationService(listing_repo=FakeListingRepository(pool), uf_service=FakeUFService())
    from services.listing_analysis import _valuation_input
    data, _ = _valuation_input(_target())
    result = await service.valuate_property(data)
    assert result.comparable_count == 5


def test_radar_and_enrichment_exclude_duplicate_publications():
    from domain.radar.detector import _exclude_self
    from services.radar import _same_listing
    pool = _pool(5)
    duplicate = replace(pool[1], external_id=pool[0].external_id)
    assert _exclude_self(pool[0], [pool[0], duplicate, pool[2]]) == [pool[2]]
    assert _same_listing(pool[0], duplicate)
    assert not _same_listing(pool[0], pool[2])
