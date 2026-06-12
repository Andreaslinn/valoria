from __future__ import annotations

from api.v1.alerts import _alert_message


def test_price_drop_message_uses_uf_when_change_basis_is_uf() -> None:
    message = _alert_message(
        "price_drop",
        {
            "canonical_previous_price": 3250,
            "canonical_new_price": 3200,
            "canonical_price_unit": "UF",
            "previous_price_clp_snapshot": 132_259_985,
            "new_price_clp_snapshot": 118_400_000,
            "change_basis": "uf",
            "drop_pct": 1.54,
        },
    )

    assert "UF 3.250 a UF 3.200" in message
    assert "Equivalente CLP snapshot" in message


def test_price_drop_message_uses_clp_for_clp_basis() -> None:
    message = _alert_message(
        "price_drop",
        {
            "canonical_previous_price": 100_000_000,
            "canonical_new_price": 90_000_000,
            "canonical_price_unit": "CLP",
            "change_basis": "clp",
            "drop_pct": 10,
        },
    )

    assert "$100,000,000 a $90,000,000" in message
