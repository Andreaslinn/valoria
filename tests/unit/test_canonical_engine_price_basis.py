from dataclasses import replace
from decimal import Decimal

import pytest

from core.value_objects.price import Price
from core.value_objects.score import Score
from domain.valuation.engines.canonical_comparables import (
    ComparablesCanonicalEngine,
    _weighted_mean_ppm2,
)
from domain.valuation.engines.contracts import EngineContext, EngineRequest, EngineStatus
from domain.valuation.price_surface import SurfaceAdjustmentResult
from tests.unit.factories import make_listing, make_property

UF = Decimal("41152.13")
FLORIDA_COMPARABLES = [
    (80, 4185), (77, 4500), (77, 3997), (87, 5900), (76, 3900),
    (74, 3760), (72, 3096), (71, 2650), (70, 2650), (80, 3099),
    (68, 2588), (68, 2849), (68, 4097), (74, 7500), (70, 2673),
    (69, 3173), (73, 3095), (67, 3251), (67, 2587), (83, 4462),
]


def _fixture():
    target = make_property(comuna="la_florida", m2=82, bedrooms=3, bathrooms=2, parking=1, coords=None, geocode_precision=None)
    listings = [
        make_listing(
            fingerprint=f"florida-{i}", comuna="la_florida", m2=area,
            bedrooms=3, bathrooms=2, parking=1, coords=None, geocode_precision=None,
            price_currency="UF", price_uf=price, price_uf_source="scraped",
            price_clp=Decimal(price) * UF,
        )
        for i, (area, price) in enumerate(FLORIDA_COMPARABLES)
    ]
    return target, listings


def _run(target, listings):
    return ComparablesCanonicalEngine(name="comparables_canonical_outliers", variant="outliers").valuate(
        EngineRequest(published_price_provided=True),
        EngineContext(target=target, candidates=listings, uf_to_clp=UF),
    )


def test_la_florida_base_ppm2_regression():
    target, listings = _fixture()
    result = _run(target, listings)
    assert result.status == EngineStatus.OK
    debug = result.diagnostics["result"]
    assert 44 <= debug["ppm2_base"] <= 52
    assert debug["ppm2_unit"] == "UF/m2"
    assert debug["ppm2_after_surface"] == pytest.approx(float(result.estimated_price_clp) / float(UF) / 82)
    assert debug["ppm2_after_surface"] == pytest.approx(debug["ppm2_base"] * debug["price_surface_factor"])


@pytest.mark.parametrize("snapshot_rate", [Decimal("35000"), UF * 2])
def test_weighted_mean_uses_native_uf_despite_inconsistent_clp(snapshot_rate):
    _, listings = _fixture()
    scores = [Score(0.9 - i * 0.01) for i in range(len(listings))]
    original = list(zip(scores, listings, strict=True))
    inconsistent = [(score, replace(listing, price=Price(clp=listing.price_uf * snapshot_rate))) for score, listing in original]
    assert _weighted_mean_ppm2(inconsistent, UF) == _weighted_mean_ppm2(original, UF)


def test_full_engine_ignores_uf_listing_clp_snapshot():
    target, listings = _fixture()
    original = _run(target, listings)
    inconsistent = _run(target, [replace(item, price=Price(clp=item.price_uf * UF * 2)) for item in listings])
    assert original.status == inconsistent.status == EngineStatus.OK
    assert original.estimated_price_uf == inconsistent.estimated_price_uf
    assert original.diagnostics["result"]["ppm2_base"] == inconsistent.diagnostics["result"]["ppm2_base"]
    assert original.diagnostics["result"]["comparable_weights"] == inconsistent.diagnostics["result"]["comparable_weights"]
    assert original.diagnostics["exclusions"] == inconsistent.diagnostics["exclusions"]


def test_weighted_mean_preserves_clp_native_basis():
    listing = make_listing(price_currency="CLP", price_clp=100_000_000, price_uf=9999, m2=50)
    ppm2 = _weighted_mean_ppm2([(Score(1), listing)], UF)
    expected_uf = (Decimal(100_000_000) / UF).quantize(Decimal("0.01"))
    assert ppm2 == expected_uf / 50 * UF


def test_surface_debug_exposes_actual_multiplier(monkeypatch):
    target, listings = _fixture()
    def adjust(estimate, surface, target):
        return SurfaceAdjustmentResult(
            adjusted_estimate=estimate * 1.1, adjustment_applied=True,
            adjustment_weight=0.2, adjustment_reason="controlled_surface", warnings=(),
        )
    monkeypatch.setattr("domain.valuation.engines.canonical_comparables.maybe_apply_surface_adjustment", adjust)
    result = _run(target, listings)
    assert result.status == EngineStatus.OK
    debug = result.diagnostics["result"]
    assert debug["price_surface_factor"] == pytest.approx(1.1, abs=1e-8)
    assert debug["ppm2_after_surface"] == pytest.approx(debug["ppm2_base"] * debug["price_surface_factor"])
