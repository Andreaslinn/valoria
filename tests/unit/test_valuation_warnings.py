from __future__ import annotations

from ui.redesign.valuation_warnings import map_valuation_warnings, summarize_valuation_warnings


def test_known_warning_maps_to_human_label() -> None:
    details = map_valuation_warnings(["poor_geocoding_comparables"])

    assert details[0].known is True
    assert details[0].human_label == "Comparables con ubicacion debil"
    assert details[0].short_description
    assert details[0].code == "poor_geocoding_comparables"


def test_unknown_warning_stays_technical_and_keeps_raw_code() -> None:
    details = map_valuation_warnings(["future_backend_warning"])

    assert details[0].known is False
    assert details[0].technical_only is True
    assert details[0].visible_by_default is False
    assert details[0].human_label == "Warning tecnico no mapeado"
    assert details[0].code == "future_backend_warning"


def test_warning_summary_counts_and_deduplicates_raw_codes() -> None:
    summary = summarize_valuation_warnings(
        [
            "single_source_comparables",
            "single_source_comparables",
            "weak_microzone",
        ]
    )

    assert summary.count == 2
    assert summary.data_quality_label == "media"
    assert summary.headline == "Calidad de datos: media - 2 detalles tecnicos"
    assert "single_source_comparables" not in summary.headline
    assert "weak_microzone" not in summary.headline
    assert [detail.code for detail in summary.details] == ["single_source_comparables", "weak_microzone"]
