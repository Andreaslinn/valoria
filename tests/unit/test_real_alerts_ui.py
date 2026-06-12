from __future__ import annotations

from ui.pages.alerts_real import _alert_message


def test_price_drop_message_formats_payload() -> None:
    message = _alert_message(
        {
            "alert_type": "price_drop",
            "payload": {
                "previous_price_clp": 100_000_000,
                "new_price_clp": 90_000_000,
                "drop_pct": 10,
            },
        }
    )

    assert "bajo" in message
    assert "$100.000.000" in message
    assert "$90.000.000" in message
    assert "-10.00%" in message


def test_price_drop_message_handles_missing_payload() -> None:
    assert _alert_message({"alert_type": "price_drop", "payload": {}}) == "La propiedad bajo de precio."
    assert _alert_message({"alert_type": "other", "payload": {}}) == "Nueva alerta de la propiedad."
