from __future__ import annotations

from decimal import Decimal

from scripts.evaluation_benchmark import _exclude_leakage, _has_poor_geocoding, run_benchmark
from tests.unit.factories import make_listing

UF = Decimal("37000")


def _listing(index: int, **kwargs):
    fingerprint = kwargs.pop("fingerprint", f"fp-{index}")
    listing = make_listing(fingerprint=fingerprint, **kwargs)
    listing.id = index
    return listing


def test_exclude_leakage_removes_self_and_duplicates() -> None:
    target = _listing(1)
    same_id = _listing(1, fingerprint="different")
    same_fingerprint = _listing(2, fingerprint=target.fingerprint)
    same_external = _listing(3, fingerprint="same-external")
    same_external.external_id = target.external_id
    same_property = _listing(4, fingerprint="same-property")
    same_property.property_id = 99
    target.property_id = 99
    valid = _listing(5, fingerprint="valid")

    filtered = _exclude_leakage(target, [target, same_id, same_fingerprint, same_external, same_property, valid])

    assert filtered == [valid]


def test_run_benchmark_reports_accuracy_and_coverage() -> None:
    listings = [_listing(i, price_clp=180_000_000 + i * 1_000_000) for i in range(1, 9)]

    report = run_benchmark(listings, uf_to_clp=UF, min_samples=1)

    summary = report["summary"]
    assert summary["status"] == "ok"
    assert summary["total_active_listings"] == 8
    assert summary["successful_valuations"] == 8
    assert summary["coverage_pct"] == 100.0
    assert summary["avg_comparables_used"] == 7.0
    assert summary["surface_available_rate_pct"] == 100.0
    assert summary["surface_level_usage"]["comuna_m2_bucket"] == 8
    assert summary["surface_audit"]["surface_mape_pct"] is not None
    assert summary["surface_audit"]["blend_10_mape_pct"] is not None
    assert summary["metrics"]["mape_pct"] is not None
    assert summary["metrics"]["median_ape_pct"] is not None
    assert summary["metrics"]["mae_clp"] is not None
    assert summary["metrics"]["mae_uf"] is not None
    assert summary["metrics"]["error_percentiles_pct"]["p90"] is not None
    assert report["by_comuna"]["nunoa"]["n"] == 8
    assert report["by_comuna"]["nunoa"]["coverage_pct"] == 100.0
    assert report["by_comuna"]["nunoa"]["error_percentiles_pct"]["p90"] is not None
    assert report["by_comuna"]["nunoa"]["reliability_label"] in {"confiable", "cautela", "no_confiable"}
    assert report["by_property_type"]["apartment"]["n"] == 8
    assert report["by_m2_bucket"]["60-79"]["n"] == 8
    assert report["rows"][0]["surface_available"] is True
    assert report["rows"][0]["surface_price_m2"] is not None
    assert report["rows"][0]["surface_error_pct"] is not None
    assert report["rows"][0]["model_error_pct"] is not None
    assert report["rows"][0]["surface_beats_model"] in {True, False}
    assert report["rows"][0]["hypothetical_blend_10_pct_error"] is not None
    assert report["by_surface_level"]["comuna_m2_bucket"]["n"] == 8
    assert report["by_surface_dispersion_bucket"]
    assert report["by_surface_sample_count_bucket"]
    assert report["rankings"]["best_comunas"]


def test_run_benchmark_marks_low_data_mode() -> None:
    listings = [_listing(i) for i in range(1, 7)]

    report = run_benchmark(listings, uf_to_clp=UF, min_samples=1)

    assert report["summary"]["status"] == "ok"
    assert report["summary"]["low_data_mode_rate_pct"] == 100.0
    assert all(row["low_data_mode"] for row in report["rows"])


def test_run_benchmark_does_not_invent_metrics_with_insufficient_data() -> None:
    listings = [_listing(i) for i in range(1, 5)]

    report = run_benchmark(listings, uf_to_clp=UF, min_samples=5)

    assert report["summary"]["status"] == "insufficient_data"
    assert report["summary"]["successful_valuations"] == 0
    assert report["summary"]["metrics"] is None
    assert "No se reportan metricas" in report["summary"]["note"]
    assert report["summary"]["skip_reasons"]


def test_run_benchmark_segments_by_property_type() -> None:
    apartments = [_listing(i, property_type="apartment") for i in range(1, 7)]
    houses = [
        _listing(i, property_type="house", m2=140, built_area_m2=140, land_area_m2=300, price_clp=350_000_000)
        for i in range(10, 16)
    ]

    report = run_benchmark([*apartments, *houses], uf_to_clp=UF, min_samples=1)

    assert report["by_property_type"]["apartment"]["n"] == 6
    assert report["by_property_type"]["house"]["n"] == 6


def test_run_benchmark_does_not_mix_property_types_for_accuracy() -> None:
    apartments = [
        _listing(i, property_type="apartment", m2=75, built_area_m2=75, price_clp=180_000_000)
        for i in range(1, 7)
    ]
    houses = [
        _listing(i, property_type="house", m2=140, built_area_m2=140, land_area_m2=300, price_clp=700_000_000)
        for i in range(10, 16)
    ]

    report = run_benchmark([*apartments, *houses], uf_to_clp=UF, min_samples=1)

    assert report["by_property_type"]["apartment"]["mae_clp"] == 0.0
    assert report["by_property_type"]["house"]["mae_clp"] == 0.0
    assert report["by_property_type"]["apartment"]["coverage_pct"] == 100.0
    assert report["by_property_type"]["house"]["coverage_pct"] == 100.0


def test_run_benchmark_reports_insufficient_data_by_property_type() -> None:
    apartments = [_listing(i, property_type="apartment") for i in range(1, 7)]
    houses = [
        _listing(i, property_type="house", m2=140, built_area_m2=140, land_area_m2=300, price_clp=350_000_000)
        for i in range(10, 14)
    ]

    report = run_benchmark([*apartments, *houses], uf_to_clp=UF, min_samples=1)

    assert report["by_property_type"]["apartment"]["coverage_pct"] == 100.0
    assert report["by_property_type"]["house"]["coverage_pct"] == 0.0
    assert report["by_property_type"]["house"]["insufficient_data_rate_pct"] == 100.0
    assert report["by_property_type"]["house"]["mape_pct"] is None


def test_run_benchmark_segments_by_m2_bucket() -> None:
    small = [_listing(i, m2=45, built_area_m2=45, price_clp=120_000_000) for i in range(1, 7)]
    medium = [_listing(i, m2=95, built_area_m2=95, price_clp=240_000_000) for i in range(10, 16)]

    report = run_benchmark([*small, *medium], uf_to_clp=UF, min_samples=1)

    assert report["by_m2_bucket"]["40-59"]["n"] == 6
    assert report["by_m2_bucket"]["80-119"]["n"] == 6


def test_run_benchmark_flags_poor_geocoding_and_price_dispersion() -> None:
    listings = [
        _listing(i, geocode_precision="unknown", price_clp=100_000_000 + i * 80_000_000)
        for i in range(1, 9)
    ]

    report = run_benchmark(listings, uf_to_clp=UF, min_samples=1)

    metrics = report["by_comuna"]["nunoa"]
    assert "geocoding_pobre" in metrics["risk_flags"]
    assert "alta_dispersion_precio_m2" in metrics["risk_flags"]


def test_benchmark_treats_address_without_coordinates_as_poor_geocoding() -> None:
    listing = _listing(1, coords=None, geocode_precision="address")

    assert _has_poor_geocoding(listing)
