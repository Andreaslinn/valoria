from __future__ import annotations

from decimal import Decimal

from scripts.backfill_price_history_provenance import is_uf_rate_artifact


def test_detects_uf_rate_artifact_when_clp_delta_matches_rate_delta() -> None:
    assert is_uf_rate_artifact(
        history_price_clp=Decimal("132259985"),
        current_price_clp=Decimal("120250000"),
        listing_price_uf=Decimal("3250"),
        currency="UF",
    )


def test_does_not_mark_real_uf_change_as_rate_artifact() -> None:
    assert not is_uf_rate_artifact(
        history_price_clp=Decimal("120250000"),
        current_price_clp=Decimal("118400000"),
        listing_price_uf=Decimal("3200"),
        currency="UF",
    )


def test_does_not_mark_clp_listing_as_rate_artifact() -> None:
    assert not is_uf_rate_artifact(
        history_price_clp=Decimal("180000000"),
        current_price_clp=Decimal("170000000"),
        listing_price_uf=None,
        currency="CLP",
    )
