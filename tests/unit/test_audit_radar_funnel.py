"""Unit tests for the read-only Radar funnel audit script."""
from __future__ import annotations

from scripts.audit_radar_funnel import (
    comparable_count_bucket,
    confidence_bucket,
    quantiles,
)


def test_quantiles_empty_values() -> None:
    assert quantiles([]) == {
        "min": None,
        "p10": None,
        "p25": None,
        "p50": None,
        "p75": None,
        "p90": None,
        "p95": None,
        "p99": None,
        "max": None,
    }


def test_quantiles_interpolates_percentiles() -> None:
    result = quantiles([1, 2, 3, 4, 5])

    assert result["min"] == 1
    assert result["p50"] == 3
    assert result["p90"] == 4.6
    assert result["max"] == 5


def test_confidence_bucket_boundaries() -> None:
    assert confidence_bucket(None) == "missing"
    assert confidence_bucket(0.29) == "<0.30"
    assert confidence_bucket(0.3) == "0.30-0.49"
    assert confidence_bucket(0.5) == "0.50-0.74"
    assert confidence_bucket(0.75) == ">=0.75"


def test_comparable_count_bucket_boundaries() -> None:
    assert comparable_count_bucket(None) == "missing"
    assert comparable_count_bucket(4) == "<5"
    assert comparable_count_bucket(5) == "5-9"
    assert comparable_count_bucket(10) == "10-19"
    assert comparable_count_bucket(20) == ">=20"
