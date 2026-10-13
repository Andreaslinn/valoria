"""Offline regression: displayed prices compared with captured numeric payloads."""
import json
from decimal import Decimal
from html import escape
from pathlib import Path

import pytest

from infrastructure.scrapers.yapo import YapoScraper, _parse_modern_price


CAPTURE = json.loads((Path(__file__).parents[1] / "fixtures/yapo_dom_prices_20260929.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("item", CAPTURE, ids=lambda item: item["id"])
def test_actual_dom_price_matches_independent_structured_amount(item):
    html = (f'<a class="item-card-link" href="{escape(item["url"])}">'
            f'<h3 class="card_title">{escape(item["title"])}</h3>'
            f'<span class="card_price">{escape(item["display_price"])}</span></a>')
    row, = YapoScraper.parse_listings(html, uf_to_clp=Decimal("41049.01"))
    amount = Decimal(str(item["amount"]))
    is_uf = item["currency"] == "CLF"
    assert row["external_id"] == item["id"]
    assert row["price_clp"] == int(amount * Decimal("41049.01") if is_uf else amount)
    assert row["price_uf"] == (float(amount) if is_uf else None)


@pytest.mark.parametrize("text,expected", [
    ("UF 9,950.50", ("UF", Decimal("9950.50"))),
    ("UF 9.950,50", ("UF", Decimal("9950.50"))),
    ("UF 3.355", ("UF", Decimal("3355"))),
    ("UF 25.50", ("UF", Decimal("25.50"))),
    ("$ 1", ("CLP", Decimal("1"))),
    ("$ 3,008", ("CLP", Decimal("3008"))),
    ("UF 9,950 mensual", None),
])
def test_formats_preserve_low_values_and_reject_extra_text(text, expected):
    assert _parse_modern_price(text) == expected
