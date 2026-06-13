from __future__ import annotations

from decimal import Decimal

from domain.valuation.engines.canonical_comparables import ComparablesCanonicalEngine
from domain.valuation.engines.contracts import EngineContext, EngineRequest, EngineStatus
from tests.unit.factories import make_listing, make_property

UF = Decimal("40000")


def _run(target, candidates, *, variant: str = "full", name: str | None = None, uf=UF):
    return ComparablesCanonicalEngine(name=name, variant=variant).valuate(
        EngineRequest(published_price_provided=True),
        EngineContext(target=target, candidates=candidates, uf_to_clp=uf),
    )


def _listing(idx: int, *, price=200_000_000, title: str | None = None, property_type="house"):
    return make_listing(
        fingerprint=f"c-{idx}",
        property_type=property_type,
        title=title or "Casa familiar",
        m2=100,
        built_area_m2=100,
        price_clp=price,
        price_currency="CLP",
    )


def test_canonical_engine_values_house_and_reports_diagnostics() -> None:
    target = make_property(
        property_type="house",
        m2=100,
        built_area_m2=100,
        raw_metadata={"title": "Casa familiar en barrio residencial"},
    )
    listings = [_listing(idx, price=200_000_000 + idx * 1_000_000) for idx in range(6)]

    result = _run(target, listings)

    assert result.status == EngineStatus.OK
    assert result.engine_name == "comparables_canonical"
    assert result.engine_version == "phase1_canonical_v1"
    assert result.comparables_used == 6
    assert result.estimated_price_clp is not None
    assert result.range_low_clp is not None
    assert result.confidence is not None
    assert result.diagnostics["pool"]["canonical_price_usable"] == 6
    assert result.diagnostics["product"]["target_product_class"] == "standard_residential"
    assert result.to_dict()["engine_name"] == "comparables_canonical"


def test_canonical_engine_excludes_special_product_candidate() -> None:
    target = make_property(
        property_type="house",
        m2=100,
        built_area_m2=100,
        raw_metadata={"title": "Casa familiar"},
    )
    listings = [_listing(idx) for idx in range(5)]
    listings.append(_listing(99, price=190_000_000, title="Sitio en venta"))

    result = _run(target, listings, variant="product")

    assert result.status == EngineStatus.OK
    assert result.comparables_used == 5
    assert result.diagnostics["exclusions"]["product_incompatible"] == 1


def test_canonical_engine_excludes_high_price_m2_outlier() -> None:
    target = make_property(property_type="house", m2=100, built_area_m2=100)
    listings = [_listing(idx, price=200_000_000) for idx in range(8)]
    listings.append(_listing(99, price=600_000_000))

    result = _run(target, listings, variant="outliers")

    assert result.status == EngineStatus.OK
    assert result.diagnostics["exclusions"]["price_m2_high_outlier"] == 1
    assert "fp:c-99" not in result.diagnostics["selected_comparable_fingerprints"]


def test_canonical_outliers_variant_is_phase4a_canonical_plus_outliers() -> None:
    engine = ComparablesCanonicalEngine(name="comparables_canonical_outliers", variant="outliers")

    assert engine.name == "comparables_canonical_outliers"
    assert engine.version == "phase4a_canonical_outliers_v1"
    assert engine.config.config_version == "phase4a_canonical_outliers_v1"
    assert engine.config.canonical_price_enabled is True
    assert engine.config.enable_product_filter is False
    assert engine.config.product_hard_filtering_mode == "disabled"
    assert engine.config.enable_robust_filter is True
    assert engine.config.robust_filter.min_iqr_samples == 8
    assert engine.config.robust_filter.min_percentile_samples == 5
    assert engine.config.robust_filter.iqr_multiplier == 2.0
    assert engine.config.robust_filter.fallback_iqr_multiplier == 2.75
    assert engine.config.robust_filter.max_deviation_ratio == 2.25
    assert engine.config.robust_filter.min_deviation_ratio == 0.35
    assert engine.config.robust_filter.house_high_tail_ratio == 1.85


def test_canonical_outliers_reports_required_flat_diagnostics() -> None:
    target = make_property(property_type="house", m2=100, built_area_m2=100)
    listings = [_listing(idx, price=200_000_000 + idx * 1_000_000) for idx in range(8)]
    listings.append(_listing(99, price=600_000_000))

    result = _run(
        target,
        listings,
        name="comparables_canonical_outliers",
        variant="outliers",
    )

    assert result.status == EngineStatus.OK
    assert result.engine_name == "comparables_canonical_outliers"
    assert result.engine_version == "phase4a_canonical_outliers_v1"
    assert result.diagnostics["variant"] == "outliers"
    assert result.diagnostics["config_version"] == "phase4a_canonical_outliers_v1"
    assert result.diagnostics["canonical_price_enabled"] is True
    assert result.diagnostics["product_filter_enabled"] is False
    assert result.diagnostics["robust_filter_enabled"] is True
    assert result.diagnostics["candidates_loaded"] == 9
    assert result.diagnostics["structurally_eligible"] == 9
    assert result.diagnostics["canonical_price_usable"] == 9
    assert result.diagnostics["robust_filter_input"] == 9
    assert result.diagnostics["robust_filter_output"] == 8
    assert result.diagnostics["high_outliers_excluded"] == 1
    assert result.diagnostics["low_outliers_excluded"] == 0
    assert result.diagnostics["fallback_applied"] is False
    assert result.diagnostics["selected_comparables"] == 8
    assert result.diagnostics["comparables_used"] == 8
    assert result.diagnostics["local_reference_level"] is not None
    assert result.diagnostics["local_median_price_m2"] is not None
    assert result.diagnostics["lower_threshold"] is not None
    assert result.diagnostics["upper_threshold"] is not None
    assert result.diagnostics["threshold_method"] is not None
    assert isinstance(result.diagnostics["confidence_penalties"], list)
    assert result.diagnostics["price_basis_by_comparable"]
    assert result.diagnostics["estimate_before_outlier_filter"] is not None
    assert result.diagnostics["estimate_after_outlier_filter"] is not None


def test_canonical_outliers_excludes_low_price_m2_outlier() -> None:
    target = make_property(property_type="house", m2=100, built_area_m2=100)
    prices = [10_000_000, 200_000_000, 210_000_000, 220_000_000, 230_000_000, 240_000_000, 250_000_000, 260_000_000, 270_000_000]
    listings = [_listing(idx, price=price) for idx, price in enumerate(prices)]

    result = _run(target, listings, variant="outliers")

    assert result.status == EngineStatus.OK
    assert result.diagnostics["low_outliers_excluded"] == 1
    assert "fp:c-0" not in result.diagnostics["selected_comparable_fingerprints"]


def test_canonical_outliers_uses_relaxed_fallback_when_strict_filter_is_too_small() -> None:
    target = make_property(property_type="house", m2=100, built_area_m2=100)
    ppm2_values = [100, 100, 100, 110, 500, 500, 500, 600]
    listings = [_listing(idx, price=ppm2 * 100) for idx, ppm2 in enumerate(ppm2_values)]

    result = _run(target, listings, variant="outliers")

    assert result.status == EngineStatus.OK
    assert result.diagnostics["fallback_applied"] is True
    assert result.diagnostics["robust_filter_output"] == 5
    assert "robust_filter_relaxed" in result.warnings


def test_canonical_outliers_requires_minimum_data_after_filtering() -> None:
    target = make_property(property_type="house", m2=100, built_area_m2=100)
    listings = [_listing(idx, price=200_000_000) for idx in range(4)]

    result = _run(target, listings, variant="outliers")

    assert result.status == EngineStatus.INSUFFICIENT_DATA
    assert result.error_code == "insufficient_data"


def test_canonical_engine_rejects_legacy_unrecoverable_and_low_confidence_prices() -> None:
    target = make_property(property_type="apartment", m2=75, built_area_m2=75)
    good = [
        make_listing(
            fingerprint=f"good-{idx}",
            price_clp=180_000_000,
            price_currency="UF",
            price_uf=Decimal("4500"),
            price_uf_source="scraped",
            price_uf_confidence="high",
        )
        for idx in range(5)
    ]
    bad = [
        make_listing(
            fingerprint="legacy",
            price_clp=166_500_000,
            price_currency="UF",
            price_uf=Decimal("4500"),
            price_uf_source="legacy_unrecoverable",
            price_uf_confidence="low",
        ),
        make_listing(
            fingerprint="estimated",
            price_clp=180_000_000,
            price_currency="UF",
            price_uf=Decimal("4500"),
            price_uf_source="estimated",
            price_uf_confidence="low",
        ),
    ]

    result = _run(target, [*good, *bad], variant="price_only")

    assert result.status == EngineStatus.OK
    assert result.diagnostics["exclusions"]["legacy_unrecoverable"] == 1
    assert result.diagnostics["exclusions"]["low_confidence_estimated"] == 1


def test_canonical_engine_refuses_37000_uf_rate() -> None:
    target = make_property(property_type="apartment", m2=75)
    listings = [_listing(idx, property_type="apartment") for idx in range(5)]

    result = _run(target, listings, uf=Decimal("37000"))

    assert result.status == EngineStatus.VALIDATION_ERROR
    assert result.error_code == "validation_error"


def test_canonical_engine_reports_insufficient_data_after_filters() -> None:
    target = make_property(
        property_type="house",
        m2=100,
        built_area_m2=100,
        raw_metadata={"title": "Casa familiar"},
    )
    listings = [_listing(idx, title="Sitio en venta") for idx in range(5)]

    result = _run(target, listings, variant="product")

    assert result.status == EngineStatus.INSUFFICIENT_DATA
