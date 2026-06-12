from __future__ import annotations

from ui.components.risk_report_html import build_risk_report_html, build_valuation_risk_report_data


def test_valuation_risk_report_data_maps_url_analysis_result() -> None:
    payload = {
        "comuna": "nunoa",
        "property_type": "apartment",
        "m2": 75.0,
        "built_area_m2": 75.0,
        "precio_publicado_clp": 180_000_000,
    }
    result = {
        "estimated_price_uf": 5200.0,
        "estimated_price_clp": 205_000_000,
        "price_range_low_uf": 4900.0,
        "price_range_high_uf": 5500.0,
        "confidence": "medium",
        "comparable_count": 6,
        "price_m2_uf": 69.33,
        "warnings": [],
        "comparables": [
            {
                "listing_id": 10,
                "title": "Comparable",
                "comuna": "nunoa",
                "price_uf": 5100.0,
                "m2": 74.0,
                "similarity": 0.82,
            }
        ],
    }
    lookup = {
        "status": "found_existing",
        "url": "https://www.yapo.cl/bienes-raices/test/123",
        "source": "yapo",
        "warnings": [],
        "listing_data": {"listing_id": 950, "title": "Depto test", "url": "https://www.yapo.cl/bienes-raices/test/123"},
    }

    report_data = build_valuation_risk_report_data(result, payload, lookup)
    html = build_risk_report_html(report_data)

    assert report_data["header"]["listing_id"] == 950
    assert report_data["reliability"]["missing"] == []
    assert "Valuation Analysis" in html
    assert "Data Reliability" in html
    assert "Comparable 1" in html


def test_valuation_risk_report_marks_missing_listing_id_for_watchlist() -> None:
    payload = {
        "comuna": "nunoa",
        "property_type": "apartment",
        "m2": 75.0,
        "built_area_m2": 75.0,
    }
    result = {
        "estimated_price_uf": 5200.0,
        "estimated_price_clp": 205_000_000,
        "confidence": "low",
        "comparable_count": 2,
        "warnings": ["published_price_not_provided"],
        "comparables": [],
    }

    report_data = build_valuation_risk_report_data(result, payload, {"status": "parsed_new", "listing_data": {}})

    assert report_data["header"]["listing_id"] == "N/A"
    assert "precio publicado" in report_data["reliability"]["missing"]
    assert "listing id para watchlist" in report_data["reliability"]["missing"]
