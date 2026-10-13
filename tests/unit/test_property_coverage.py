from dataclasses import replace
import pytest
from core.exceptions import InsufficientDataError, ValidationError
from core.normalization.property_consistency import property_type_conflict
from services.valuation import ValuationInput, ValuationService
from tests.unit.factories import make_listing
from tests.unit.test_valuation_service import FakeListingRepository, FakeUFService


@pytest.mark.parametrize("count", [0,4,5])
async def test_office_coverage_keeps_minimum_comparable_safeguard(count):
    pool=[replace(make_listing(property_type="office",fingerprint=f"office-{i}"),id=i+1) for i in range(count)]
    service=ValuationService(listing_repo=FakeListingRepository(pool),uf_service=FakeUFService())
    data=ValuationInput(comuna="nunoa",property_type="office",m2=75)
    if count<5:
        with pytest.raises(InsufficientDataError):await service.valuate_property(data)
    else:
        assert (await service.valuate_property(data)).estimated_price_uf>0


async def test_6842_title_category_contradiction_blocks_automatic_valuation():
    target=replace(make_listing(title="Imperdible !!! Casa En Venta , Excelente Ubicacion A Pasos Del Metro Las Torres.",property_type="apartment"),id=6842)
    assert property_type_conflict(target)
    service=ValuationService(listing_repo=FakeListingRepository([target]),uf_service=FakeUFService())
    with pytest.raises(ValidationError,match="contradicen"):
        await service.valuate_property(ValuationInput(comuna="nunoa",property_type="apartment",m2=75,target_listing_id=6842))


def test_ambiguous_or_similar_title_is_not_automatically_reclassified():
    assert not property_type_conflict(make_listing(title="Cerca de casa central"))
    assert not property_type_conflict(make_listing(title="Casa en venta o departamento en venta"))
