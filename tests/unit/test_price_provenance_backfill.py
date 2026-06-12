from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from infrastructure.db.models import ListingORM
from scripts.backfill_price_provenance import (
    build_suggestions,
    extract_title_price_ufs,
    observed_rates_by_date,
)


def _listing(
    *,
    listing_id: int,
    title: str = "Departamento en venta",
    price_clp: Decimal = Decimal("406953800"),
    raw_metadata: dict | None = None,
    scraped_at: datetime | None = None,
) -> ListingORM:
    return ListingORM(
        id=listing_id,
        source="yapo",
        external_id=str(listing_id),
        title=title,
        url=f"https://example.test/{listing_id}",
        comuna="nunoa",
        property_type="apartment",
        m2=100,
        bedrooms=2,
        bathrooms=2,
        parking=1,
        price_clp=price_clp,
        status="active",
        fingerprint=f"fp-{listing_id}",
        raw_metadata=raw_metadata or {"currency_original": "UF"},
        scraped_at=scraped_at or datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
        last_seen_at=scraped_at or datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
    )


def test_extract_title_price_uf_with_thousands_separator() -> None:
    assert extract_title_price_ufs("Casa en venta UF 10.500") == [Decimal("10500")]
    assert extract_title_price_ufs("Departamento 4526UF") == [Decimal("4526")]


def test_existing_raw_metadata_price_uf_is_scraped() -> None:
    listing = _listing(
        listing_id=1,
        price_clp=Decimal("406953800"),
        raw_metadata={"currency_original": "UF", "price_uf": 10000},
    )

    suggestion = build_suggestions([listing])[0]

    assert suggestion.suggested_price_uf == "10000.00"
    assert suggestion.suggested_price_uf_source == "scraped"
    assert suggestion.suggested_price_uf_confidence == "high"


def test_title_price_uf_is_recovered_exact() -> None:
    listing = _listing(
        listing_id=2,
        title="Departamento Providencia 4526UF",
        price_clp=Decimal("184187289"),
    )

    suggestion = build_suggestions([listing])[0]

    assert suggestion.suggested_price_uf == "4526.00"
    assert suggestion.suggested_price_uf_source == "recovered_exact"
    assert suggestion.suggested_price_recovery_method == "title_explicit_uf"


def test_same_day_observed_rate_recovers_high_confidence() -> None:
    observed = _listing(
        listing_id=3,
        price_clp=Decimal("406953800"),
        raw_metadata={"currency_original": "UF", "price_uf": 10000},
    )
    missing = _listing(
        listing_id=4,
        price_clp=Decimal("203476900"),
        raw_metadata={"currency_original": "UF"},
    )

    suggestion = [item for item in build_suggestions([observed, missing]) if item.listing_id == 4][0]

    assert suggestion.suggested_price_uf == "5000.00"
    assert suggestion.suggested_price_uf_source == "recovered_high_confidence"
    assert suggestion.suggested_price_recovery_method == "same_day_observed_rate_integer"


def test_unrecoverable_is_skipped_by_default_and_marked_when_requested() -> None:
    listing = _listing(
        listing_id=5,
        scraped_at=datetime(2026, 5, 12, 12, 0, tzinfo=UTC),
        price_clp=Decimal("123456789"),
        raw_metadata={"currency_original": "UF"},
    )

    assert build_suggestions([listing]) == []

    suggestion = build_suggestions([listing], include_legacy_unrecoverable=True)[0]
    assert suggestion.suggested_price_uf is None
    assert suggestion.suggested_price_uf_source == "legacy_unrecoverable"


def test_clp_rows_are_only_included_when_requested() -> None:
    listing = _listing(
        listing_id=6,
        price_clp=Decimal("100000000"),
        raw_metadata={"currency_original": "CLP"},
    )

    assert build_suggestions([listing]) == []

    suggestion = build_suggestions([listing], include_clp=True)[0]
    assert suggestion.suggested_price_currency == "CLP"
    assert suggestion.suggested_price_uf is None
    assert suggestion.suggested_price_uf_source == "scraped"


def test_observed_rates_by_date_ignores_missing_price_uf() -> None:
    observed = _listing(
        listing_id=7,
        price_clp=Decimal("370000000"),
        raw_metadata={"currency_original": "UF", "price_uf": 10000},
    )
    missing = _listing(listing_id=8, price_clp=Decimal("185000000"))

    rates = observed_rates_by_date([observed, missing])

    assert rates["2026-06-05"][Decimal("37000.00")] == 1
