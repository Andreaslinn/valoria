from __future__ import annotations

from decimal import Decimal

from domain.valuation.canonical_price import valuation_price_basis

from tests.unit.factories import make_listing


UF_RATE = Decimal("37000")


def test_uf_canonical_price_does_not_change_with_clp_snapshot() -> None:
    listing_a = make_listing(
        price_clp=140_000_000,
        price_currency="UF",
        price_uf=Decimal("4000"),
        price_uf_source="scraped",
        price_uf_confidence="high",
    )
    listing_b = make_listing(
        price_clp=180_000_000,
        price_currency="UF",
        price_uf=Decimal("4000"),
        price_uf_source="scraped",
        price_uf_confidence="high",
    )

    basis_a = valuation_price_basis(listing_a, UF_RATE)
    basis_b = valuation_price_basis(listing_b, UF_RATE)

    assert basis_a.is_usable_for_valuation is True
    assert basis_b.is_usable_for_valuation is True
    assert basis_a.amount_uf == Decimal("4000.00")
    assert basis_b.amount_uf == Decimal("4000.00")
    assert basis_a.amount_clp_display == Decimal("148000000")
    assert basis_b.amount_clp_display == Decimal("148000000")
    assert basis_a.basis_used == "canonical_uf"


def test_clp_price_is_converted_to_uf_for_the_run() -> None:
    listing = make_listing(
        price_clp=37_000_000,
        price_currency="CLP",
        price_uf=None,
    )

    basis = valuation_price_basis(listing, UF_RATE)

    assert basis.is_usable_for_valuation is True
    assert basis.price_unit == "CLP"
    assert basis.basis_used == "canonical_clp_converted"
    assert basis.quality == "canonical_clp"
    assert basis.amount_uf == Decimal("1000.00")
    assert basis.amount_clp_display == Decimal("37000000.00")
    assert basis.weight_factor == Decimal("1")


def test_legacy_uf_without_price_uf_is_excluded() -> None:
    listing = make_listing(
        price_clp=148_000_000,
        price_currency="UF",
        price_uf=None,
        price_uf_source="legacy_unrecoverable",
        price_recovery_method="legacy_unrecoverable",
    )

    basis = valuation_price_basis(listing, UF_RATE)

    assert basis.is_usable_for_valuation is False
    assert basis.basis_used == "excluded_legacy_uf_missing_price_uf"
    assert basis.quality == "legacy_unrecoverable"
    assert basis.exclusion_reason == "legacy_uf_missing_price_uf"
    assert basis.weight_factor == Decimal("0")


def test_estimated_uf_is_excluded_in_strict_phase_one() -> None:
    listing = make_listing(
        price_clp=148_000_000,
        price_currency="UF",
        price_uf=Decimal("4000"),
        price_uf_source="estimated",
        price_uf_confidence="medium",
    )

    basis = valuation_price_basis(listing, UF_RATE)

    assert basis.is_usable_for_valuation is False
    assert basis.basis_used == "excluded_weak_uf_price"
    assert basis.quality == "estimated_uf_not_strong"
    assert basis.exclusion_reason == "estimated_uf_not_strong"
    assert basis.amount_uf == Decimal("4000.00")


def test_low_confidence_uf_is_excluded_in_strict_phase_one() -> None:
    listing = make_listing(
        price_clp=148_000_000,
        price_currency="UF",
        price_uf=Decimal("4000"),
        price_uf_source="recovered_high_confidence",
        price_uf_confidence="low",
    )

    basis = valuation_price_basis(listing, UF_RATE)

    assert basis.is_usable_for_valuation is False
    assert basis.basis_used == "excluded_weak_uf_price"
    assert basis.quality == "low_confidence_uf_not_strong"
    assert basis.exclusion_reason == "low_confidence_uf_not_strong"


def test_fallback_uf_does_not_enter_as_canonical() -> None:
    listing = make_listing(
        price_clp=148_000_000,
        price_currency="UF",
        price_uf=Decimal("4000"),
        price_uf_source="fallback",
        price_uf_confidence="high",
    )

    basis = valuation_price_basis(listing, UF_RATE)

    assert basis.is_usable_for_valuation is False
    assert basis.basis_used == "excluded_uf_fallback"
    assert basis.quality == "fallback_not_canonical"
    assert basis.exclusion_reason == "uf_fallback_not_canonical"


def test_metadata_fallback_uf_does_not_enter_as_canonical() -> None:
    listing = make_listing(
        price_clp=148_000_000,
        price_currency="UF",
        price_uf=Decimal("4000"),
        price_uf_source="scraped",
        price_uf_confidence="high",
        raw_metadata={"price_conversion_source": "uf_fallback"},
    )

    basis = valuation_price_basis(listing, UF_RATE)

    assert basis.is_usable_for_valuation is False
    assert basis.basis_used == "excluded_uf_fallback"
    assert basis.exclusion_reason == "uf_fallback_not_canonical"


def test_unknown_currency_is_excluded() -> None:
    listing = make_listing(
        price_clp=148_000_000,
        price_currency=None,
        price_uf=None,
        raw_metadata={},
    )

    basis = valuation_price_basis(listing, UF_RATE)

    assert basis.is_usable_for_valuation is False
    assert basis.basis_used == "excluded_unknown_currency"
    assert basis.exclusion_reason == "unknown_currency"
