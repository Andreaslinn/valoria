from __future__ import annotations

from ui.formatting import (
    format_clp,
    format_confidence,
    format_m2,
    format_pct,
    format_uf,
    none_dash,
)


def test_none_dash_formats_missing_values():
    assert none_dash(None) == "—"
    assert none_dash("") == "—"
    assert none_dash("nunoa") == "nunoa"


def test_money_and_unit_formatting():
    assert format_clp(123456789) == "$123.456.789"
    assert format_uf(4520.5) == "UF 4.520,50"
    assert format_m2(75) == "75,0 m²"


def test_percentage_and_confidence_formatting():
    assert format_pct(12.345) == "12,34%"
    assert format_confidence("high") == "Alta"
    assert format_confidence("medium") == "Media"
    assert format_confidence("unknown") == "No disponible"
    assert format_confidence(0.8) == "Alta"
