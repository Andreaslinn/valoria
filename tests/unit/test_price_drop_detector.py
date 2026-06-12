from __future__ import annotations

from datetime import UTC, datetime, timedelta

from domain.alerts.price_drop_detector import PricePoint, detect_price_drop_from_history

NOW = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)


def test_detects_drop_above_threshold() -> None:
    result = detect_price_drop_from_history(
        [
            {"price_clp": 100_000_000, "observed_at": NOW - timedelta(days=1)},
            {"price_clp": 94_000_000, "observed_at": NOW},
        ],
        threshold_pct=5.0,
    )

    assert result == {
        "previous_price_clp": 100_000_000,
        "new_price_clp": 94_000_000,
        "previous_price_uf": None,
        "new_price_uf": None,
        "previous_price_clp_snapshot": 100_000_000,
        "new_price_clp_snapshot": 94_000_000,
        "price_currency": "CLP",
        "change_basis": "clp_legacy",
        "canonical_previous_price": 100_000_000,
        "canonical_new_price": 94_000_000,
        "canonical_price_unit": "CLP",
        "display_previous_price_clp": 100_000_000,
        "display_new_price_clp": 94_000_000,
        "artifact_filtered": False,
        "drop_pct": 6.0,
        "detected_at": NOW,
    }


def test_ignores_drop_below_threshold() -> None:
    assert detect_price_drop_from_history(
        [
            {"price_clp": 100_000_000, "observed_at": NOW - timedelta(days=1)},
            {"price_clp": 96_000_000, "observed_at": NOW},
        ],
        threshold_pct=5.0,
    ) is None


def test_ignores_price_increase() -> None:
    assert detect_price_drop_from_history(
        [
            {"price_clp": 100_000_000, "observed_at": NOW - timedelta(days=1)},
            {"price_clp": 104_000_000, "observed_at": NOW},
        ]
    ) is None


def test_ignores_one_entry_history() -> None:
    assert detect_price_drop_from_history([{"price_clp": 100_000_000, "observed_at": NOW}]) is None


def test_handles_previous_price_zero() -> None:
    assert detect_price_drop_from_history(
        [
            {"price_clp": 0, "observed_at": NOW - timedelta(days=1)},
            {"price_clp": 90_000_000, "observed_at": NOW},
        ]
    ) is None


def test_handles_none_prices() -> None:
    assert detect_price_drop_from_history(
        [
            {"price_clp": None, "observed_at": NOW - timedelta(days=1)},
            {"price_clp": 90_000_000, "observed_at": NOW},
        ]
    ) is None


def test_sorts_by_observed_at_correctly() -> None:
    result = detect_price_drop_from_history(
        [
            PricePoint(price_clp=90_000_000, observed_at=NOW),
            PricePoint(price_clp=100_000_000, observed_at=NOW - timedelta(days=1)),
            PricePoint(price_clp=110_000_000, observed_at=NOW - timedelta(days=2)),
        ]
    )

    assert result is not None
    assert result["previous_price_clp"] == 100_000_000
    assert result["new_price_clp"] == 90_000_000
    assert result["drop_pct"] == 10.0


def test_uf_drop_uses_canonical_uf_basis() -> None:
    result = detect_price_drop_from_history(
        [
            {
                "price_clp": 132_259_985,
                "price_clp_snapshot": 132_259_985,
                "price_uf": 3250,
                "price_currency": "UF",
                "change_basis": "uf",
                "observed_at": NOW - timedelta(days=1),
            },
            {
                "price_clp": 118_400_000,
                "price_clp_snapshot": 118_400_000,
                "price_uf": 3200,
                "price_currency": "UF",
                "change_basis": "uf_current",
                "observed_at": NOW,
            },
        ],
        threshold_pct=1.0,
    )

    assert result is not None
    assert result["previous_price_uf"] == 3250.0
    assert result["new_price_uf"] == 3200.0
    assert result["price_currency"] == "UF"
    assert result["change_basis"] == "uf"


def test_same_uf_with_different_clp_does_not_alert() -> None:
    assert detect_price_drop_from_history(
        [
            {
                "price_clp": 132_259_985,
                "price_uf": 3250,
                "price_currency": "UF",
                "observed_at": NOW - timedelta(days=1),
            },
            {
                "price_clp": 120_250_000,
                "price_uf": 3250,
                "price_currency": "UF",
                "observed_at": NOW,
            },
        ],
        threshold_pct=1.0,
    ) is None


def test_artifact_point_is_ignored() -> None:
    assert detect_price_drop_from_history(
        [
            {
                "price_clp": 132_259_985,
                "price_uf": 3250,
                "price_currency": "UF",
                "is_artifact": True,
                "observed_at": NOW - timedelta(days=1),
            },
            {
                "price_clp": 120_250_000,
                "price_uf": 3250,
                "price_currency": "UF",
                "observed_at": NOW,
            },
        ],
        threshold_pct=1.0,
    ) is None


def test_legacy_unrecoverable_uf_without_price_uf_does_not_alert() -> None:
    assert detect_price_drop_from_history(
        [
            {
                "price_clp": 132_259_985,
                "price_currency": "UF",
                "price_uf_source": "legacy_unrecoverable",
                "observed_at": NOW - timedelta(days=1),
            },
            {
                "price_clp": 120_250_000,
                "price_currency": "UF",
                "price_uf_source": "legacy_unrecoverable",
                "observed_at": NOW,
            },
        ],
        threshold_pct=1.0,
    ) is None


def test_estimated_uf_source_does_not_create_strong_alert() -> None:
    assert detect_price_drop_from_history(
        [
            {
                "price_clp": 132_259_985,
                "price_uf": 3250,
                "price_currency": "UF",
                "price_uf_source": "estimated",
                "observed_at": NOW - timedelta(days=1),
            },
            {
                "price_clp": 118_400_000,
                "price_uf": 3200,
                "price_currency": "UF",
                "price_uf_source": "estimated",
                "observed_at": NOW,
            },
        ],
        threshold_pct=1.0,
    ) is None


def test_low_confidence_uf_does_not_create_strong_alert() -> None:
    assert detect_price_drop_from_history(
        [
            {
                "price_clp": 132_259_985,
                "price_uf": 3250,
                "price_currency": "UF",
                "price_uf_confidence": "low",
                "observed_at": NOW - timedelta(days=1),
            },
            {
                "price_clp": 118_400_000,
                "price_uf": 3200,
                "price_currency": "UF",
                "price_uf_confidence": "low",
                "observed_at": NOW,
            },
        ],
        threshold_pct=1.0,
    ) is None
