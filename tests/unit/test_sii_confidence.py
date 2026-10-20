from __future__ import annotations

import copy
from decimal import Decimal

import pytest

from scripts.compare_sii_canonical import stratified_sample
from services.sii.closing_confidence import age_band, apply_rule, features, fit_rule, is_trusted


def prediction(buildings, low=90, high=110):
    return {
        "status": "ok",
        "value_uf": 100,
        "p25_uf": low,
        "p75_uf": high,
        "comparables": [{"building": b} for b in buildings],
    }


def target(year=2020):
    return {"year": year, "date": "2026-01-01", "comuna": 1, "block": 2, "building": "1|2|TEST|100"}


def test_location_counts_include_building_in_block_without_other_block_collision():
    pred = prediction(["1|2|TEST|100"] * 5 + ["1|2|OTHER|200"] * 2 + ["1|20|OTHER|300"] * 3)
    f = features(target(), pred)
    assert f["same_building"] == 5
    assert f["same_block"] == 7
    assert f["location"] == "building5"
    assert f["cell"] == "building5/0-9/10-20"


@pytest.mark.parametrize(
    ("year", "date", "expected"),
    [
        (2016, "2025-12-01", "0-9"),
        (2016, "2026-01-01", "10-19"),
        (2006, "2026-01-01", "20-39"),
        (1986, "2026-01-01", "40+"),
        (2027, "2026-01-01", "unknown"),
        (None, "2026-01-01", "unknown"),
    ],
)
def test_actual_valuation_year_defines_age(year, date, expected):
    assert age_band(year, date) == expected


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [(95, 105, "0-10"), (90, 110, "10-20"), (85, 120, "20-35"), (80, 120, "35+")],
)
def test_relative_iqr_boundaries(low, high, expected):
    assert (
        features(target(), prediction(["1|2|TEST|100"] * 10, low, high))["dispersion_band"]
        == expected
    )


def test_rule_requires_validation_support_and_error_threshold():
    def row(cell, error):
        return {"date": "2025-09-01", "features": {"cell": cell}, "ape_pct": error}

    validation = (
        [row("building5/0-9/0-10", 10)] * 30
        + [row("building5/10-19/0-10", 9)] * 29
        + [row("building5/20-39/0-10", 10.1)] * 30
    )
    rule = fit_rule(validation)
    assert rule["allowed_cells"] == ["building5/0-9/0-10"]


@pytest.mark.parametrize("date", ["2025-06-30", "2026-01-01", "2026-09-01"])
def test_holdout_or_pool_dates_cannot_fit_rule(date):
    with pytest.raises(ValueError, match="Only 2025H2"):
        fit_rule([{"date": date, "features": None, "ape_pct": None}])


def test_trust_never_uses_target_sale_price_or_holdout_error():
    rule = {"allowed_cells": ["building5/0-9/10-20"]}
    pred = prediction(["1|2|TEST|100"] * 10)
    a = target()
    b = copy.deepcopy(a)
    a.update(uf=1, ape_pct=1000)
    b.update(uf=100000, ape_pct=0)
    assert is_trusted(rule, a, pred)
    assert is_trusted(rule, b, pred)
    assert not is_trusted(rule, a, {"status": "unavailable"})


def test_stratification_is_deterministic_proportional_and_includes_sparse_age():
    rows = [
        {"raw_id": i, "year": 2020 if i < 170 else 1990 if i < 199 else None, "date": "2026-01-01"}
        for i in range(200)
    ]
    sample, allocation = stratified_sample(rows)
    assert len(sample) == 150
    assert len({r["raw_id"] for r in sample}) == 150
    assert allocation == {"0-9": 127, "20-39": 22, "unknown": 1}
    assert stratified_sample(rows) == stratified_sample(list(reversed(rows)))


def test_readonly_export_requires_explicit_enable_before_connection_settings(monkeypatch):
    import sys

    from scripts.export_canonical_baseline_readonly import main

    monkeypatch.delenv("SII_BASELINE_READONLY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["export", "--production-readonly", "--as-of", "2026-10-19"])
    with pytest.raises(SystemExit, match="SII_BASELINE_READONLY=true required"):
        main()


def test_source_freeze_is_portable_across_git_line_endings(tmp_path):
    from scripts.evaluate_sii_confidence import source_digest

    unix = tmp_path / "unix.py"
    windows = tmp_path / "windows.py"
    unix.write_bytes(b"K = 10\nweight = 0.3\n")
    windows.write_bytes(b"K = 10\r\nweight = 0.3\r\n")
    assert source_digest(unix) == source_digest(windows)
    windows.write_bytes(b"K = 11\r\nweight = 0.3\r\n")
    assert source_digest(unix) != source_digest(windows)


def test_abstention_removes_point_estimate_outside_validated_zone():
    pred = prediction(["1|2|TEST|100"] * 10)
    rule = {"allowed_cells": [], "protocol": {"version": "test"}}
    rejected = apply_rule(rule, target(), pred)
    assert rejected["status"] == "abstained"
    assert "value_uf" not in rejected
    rule["allowed_cells"] = ["building5/0-9/10-20"]
    accepted = apply_rule(rule, target(), pred)
    assert accepted["value_uf"] == pred["value_uf"]
    assert accepted["p25_uf"] == pred["p25_uf"]
    assert accepted["p75_uf"] == pred["p75_uf"]


def test_unchanged_canonical_ignores_year_in_target_metadata():
    from core.entities.listing import Property
    from domain.valuation.engines.canonical_comparables import ComparablesCanonicalEngine
    from domain.valuation.engines.contracts import EngineContext, EngineRequest
    from tests.unit.factories import make_listing

    pool = [
        make_listing(
            fingerprint=f"year-check-{i}",
            price_currency="UF",
            price_uf=Decimal(4000 + i * 10),
            price_clp=200000000,
            price_uf_source="scraped",
            m2=75,
        )
        for i in range(20)
    ]
    engine = ComparablesCanonicalEngine(variant="outliers")
    results = []
    for year in (1930, 2020):
        prop = Property(
            id=None,
            comuna=pool[0].comuna,
            m2=75,
            bedrooms=0,
            bathrooms=0,
            parking=0,
            property_type=pool[0].property_type,
            built_area_m2=75,
            usable_area_m2=75,
            raw_metadata={"construction_year": year},
        )
        results.append(
            engine.valuate(
                EngineRequest(published_price_provided=False),
                EngineContext(target=prop, candidates=pool, uf_to_clp=Decimal("41183.94")),
            )
        )
    assert all(r.is_successful for r in results)
    assert results[0].estimated_price_uf == results[1].estimated_price_uf
