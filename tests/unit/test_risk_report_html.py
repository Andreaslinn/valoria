from __future__ import annotations

from ui.components.risk_report_html import (
    build_investment_intelligence_report_data,
    build_listing_risk_report_data,
    build_risk_report_html,
    build_valuation_risk_report_data,
)


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
    assert "Data Completeness" in html
    assert "Completitud de datos" in html
    assert "Confiabilidad general" not in html
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

    report_data = build_valuation_risk_report_data(
        result,
        payload,
        {
            "status": "parsed_new",
            "url": "https://www.yapo.cl/bienes-raices/test/123",
            "source": "yapo",
            "listing_data": {},
        },
    )

    assert report_data["analysis_context"] == "LISTING_ANALYSIS"
    assert report_data["scores"]["headline_score_name"] == "listing_opportunity_score"
    assert report_data["report_type"] == "Listing Risk / Opportunity Report"
    assert report_data["header"]["listing_id"] == "N/A"
    assert "precio publicado" in report_data["reliability"]["missing"]
    assert "listing id" in report_data["reliability"]["missing"]
    assert any("Precio publicado no disponible" in item for item in report_data["risks"])
    assert "published_price_not_provided" not in " ".join(report_data["risks"])


def test_manual_property_valuation_does_not_penalize_missing_listing_fields() -> None:
    payload = {
        "comuna": "vitacura",
        "property_type": "house",
        "m2": 221.0,
        "built_area_m2": 221.0,
        "land_area_m2": 512.0,
        "dormitorios": 5,
        "banos": 5,
        "estacionamientos": 1,
    }
    result = {
        "estimated_price_uf": 16500.0,
        "estimated_price_clp": 643_500_000,
        "price_range_low_uf": 15400.0,
        "price_range_high_uf": 17600.0,
        "confidence": "medium",
        "comparable_count": 6,
        "price_m2_uf": 74.66,
        "warnings": [
            "published_price_not_provided",
            "price_surface_high_dispersion",
            "low_data_mode",
            "single_source_comparables",
            "house_land_area_weak",
        ],
        "comparables": [
            {
                "listing_id": 10,
                "title": "Comparable Vitacura",
                "comuna": "vitacura",
                "price_uf": 16200.0,
                "m2": 220.0,
                "similarity": 0.82,
            }
        ],
    }

    report_data = build_valuation_risk_report_data(result, payload, {})
    html = build_risk_report_html(report_data)

    assert report_data["analysis_context"] == "PROPERTY_VALUATION"
    assert "published_price_not_provided" not in report_data["risks"]
    assert "precio publicado" not in report_data["reliability"]["missing"]
    assert "url publicacion" not in report_data["reliability"]["missing"]
    assert "listing id para watchlist" not in report_data["reliability"]["missing"]
    joined_risks = " ".join(report_data["risks"])
    assert "Precios comparables dispersos" in joined_risks
    assert "Muestra comparable limitada" in joined_risks
    assert "Evidencia concentrada en una fuente" in joined_risks
    assert "Terreno con evidencia limitada" in joined_risks
    assert "price_surface_high_dispersion" not in joined_risks
    assert "low_data_mode" not in joined_risks
    assert "single_source_comparables" not in joined_risks
    assert "house_land_area_weak" not in joined_risks
    assert "published_price_not_provided" not in html
    assert "price_surface_high_dispersion" not in html
    assert "single_source_comparables" not in html
    assert "house_land_area_weak" not in html
    assert "listing id para watchlist" not in html
    assert "url publicacion" not in html
    assert "HIGH RISK" not in html
    assert "Listing N/A" not in html
    assert "Investment Intelligence Report" in html
    assert "La tesis de inversion" in html
    assert "publicacion muestra" not in html
    assert "Valuation Analysis" in html
    assert report_data["scores"]["headline_score_name"] == "investment_score"
    assert report_data["report_type"] == "Investment Intelligence Report"


def test_listing_analysis_uses_listing_copy_and_hides_raw_warning_codes() -> None:
    payload = {
        "comuna": "nunoa",
        "property_type": "apartment",
        "m2": 75.0,
        "built_area_m2": 75.0,
        "precio_publicado_uf": 4500.0,
        "url": "https://example.test/listing/123",
        "source": "portal",
        "listing_id": 123,
        "discount_pct": 13.4,
    }
    result = {
        "estimated_price_uf": 5200.0,
        "estimated_price_clp": 205_000_000,
        "confidence": "medium",
        "comparable_count": 5,
        "warnings": ["publication_history_missing", "legacy_uf_missing_price_uf"],
    }
    lookup = {
        "url": "https://example.test/listing/123",
        "source": "portal",
        "listing_id": 123,
        "listing_data": {
            "listing_id": 123,
            "url": "https://example.test/listing/123",
            "source": "portal",
        },
    }

    report_data = build_valuation_risk_report_data(result, payload, lookup)
    html = build_risk_report_html(report_data)

    assert report_data["analysis_context"] == "LISTING_ANALYSIS"
    assert report_data["scores"]["headline_score_name"] == "listing_opportunity_score"
    assert report_data["report_type"] == "Listing Risk / Opportunity Report"
    assert report_data["reliability"]["missing"] == []
    assert "Precio publicado" in html
    assert "Descuento" in html
    assert "Disponible" in html
    assert "Listing Risk / Opportunity Report" in html
    assert "Listing Opportunity Score" in html
    assert "La publicacion muestra una brecha positiva" in html
    assert "Historial de publicacion incompleto" in html
    assert "Precio publicado con calidad limitada" in html
    assert "publication_history_missing" not in html
    assert "legacy_uf_missing_price_uf" not in html
    assert "HIGH RISK" not in html
    assert "Strong Candidate" not in html
    assert "superficie" not in report_data["reliability"]["missing"]
    assert "Validacion legal externa" in html
    assert "No integrada" in html
    assert "NO INTEGRADO" in html
    assert "Riesgo legal" not in html
    assert "Sin senales cualitativas adicionales disponibles" not in html

    score_labels = [item["label"] for item in report_data["scores"]["items"]]
    score_weights = [item["weight"] for item in report_data["scores"]["items"]]
    assert score_labels == [
        "Price Opportunity",
        "Valuation Confidence",
        "Listing Evidence",
        "Market Context",
        "Alert / Watchlist / Price History",
    ]
    assert score_weights == [35, 25, 15, 15, 10]


def test_dual_builders_split_investment_and_listing_reports_from_url_context() -> None:
    payload = {
        "comuna": "nunoa",
        "property_type": "apartment",
        "m2": 75.0,
        "built_area_m2": 75.0,
        "precio_publicado_uf": 4500.0,
        "url": "https://example.test/listing/123",
        "source": "portal",
        "listing_id": 123,
        "discount_pct": 13.4,
    }
    result = {
        "estimated_price_uf": 5200.0,
        "estimated_price_clp": 205_000_000,
        "confidence": "medium",
        "comparable_count": 5,
        "warnings": [
            "published_price_not_provided",
            "publication_history_missing",
            "single_source_comparables",
        ],
    }
    lookup = {
        "url": "https://example.test/listing/123",
        "source": "portal",
        "listing_id": 123,
        "listing_data": {
            "listing_id": 123,
            "url": "https://example.test/listing/123",
            "source": "portal",
        },
    }

    investment = build_investment_intelligence_report_data(result, payload, lookup)
    listing = build_listing_risk_report_data(result, payload, lookup)
    investment_html = build_risk_report_html(investment)
    listing_html = build_risk_report_html(listing)

    assert investment["analysis_context"] == "PROPERTY_VALUATION"
    assert investment["report_type"] == "Investment Intelligence Report"
    assert investment["scores"]["headline_score_name"] == "investment_score"
    assert "Datos de propiedad extraidos desde publicacion" in investment_html
    assert "Tasacion manual" not in investment_html
    assert "Precio publicado no disponible" not in investment_html
    assert "Historial de publicacion incompleto" not in investment_html
    assert "listing id para watchlist" not in investment_html
    assert "Listing N/A" not in investment_html
    assert "Evidencia concentrada en una fuente" in investment_html
    assert "datos disponibles de la publicacion" not in investment["disclaimer"]
    assert "tasacion AVM, comparables y senales de mercado" in investment["disclaimer"]
    investment_score_labels = [item["label"] for item in investment["scores"]["items"]]
    investment_score_weights = [item["weight"] for item in investment["scores"]["items"]]
    assert investment_score_labels == [
        "Valuation Confidence",
        "Location / Market Context",
        "Segment Depth / Liquidity Proxy",
        "Asset Fit / Physical Profile",
        "Contextual Data Completeness",
    ]
    assert investment_score_weights == [30, 25, 20, 15, 10]
    assert "Market Support <span class=\"muted mono\">(" not in investment_html

    assert listing["analysis_context"] == "LISTING_ANALYSIS"
    assert listing["report_type"] == "Listing Risk / Opportunity Report"
    assert listing["scores"]["headline_score_name"] == "listing_opportunity_score"
    assert "Precio publicado" in listing_html
    assert "Descuento" in listing_html
    assert "Historial de publicacion incompleto" in listing_html
    assert "Listing Risk / Opportunity Report" in listing_html
    assert "published_price_not_provided" not in listing_html
    assert "precio publicado y datos disponibles de la publicacion" in listing["disclaimer"]
