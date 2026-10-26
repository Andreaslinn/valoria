from decimal import Decimal

import pytest

from scripts.diagnose_canonical_price_basis import percentile, summarize


def test_diagnostic_denominator_and_ratio_boundaries():
    rows = [
        ("yapo", Decimal("97000"), Decimal("1")),
        ("yapo", Decimal("103000"), Decimal("1")),
        ("yapo", Decimal("104000"), Decimal("1")),
        ("yapo", Decimal("100000"), None),
        ("yapo", Decimal("100000"), Decimal("0")),
    ]
    result = summarize(rows, Decimal("100000"))
    assert result["yapo"]["active_n"] == 5
    assert result["yapo"]["n"] == 3
    assert result["yapo"]["excluded_missing_or_nonpositive_n"] == 2
    assert result["yapo"]["outside_0_97_to_1_03_n"] == 1
    assert result["yapo"]["outside_0_97_to_1_03_pct"] == pytest.approx(100 / 3)
    assert result["yapo"]["median"] == 1.03
    assert result["portalinmobiliario"]["n"] == 0
    assert result["portalinmobiliario"]["median"] is None
    assert result["portalinmobiliario"]["outside_0_97_to_1_03_pct"] is None


def test_diagnostic_percentiles_use_linear_interpolation():
    assert percentile([], 0.95) is None
    assert percentile([1], 0.05) == 1
    assert percentile([4, 1, 3, 2], 0.05) == pytest.approx(1.15)
    assert percentile([4, 1, 3, 2], 0.95) == pytest.approx(3.85)
