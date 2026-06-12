from __future__ import annotations

from ui.demo_data import (
    get_demo_listings,
    get_demo_opportunities,
    get_demo_portfolio,
    get_demo_recommendations,
    get_demo_risk_report,
    get_demo_valuation_result,
)

REQUIRED_LISTING_FIELDS = {
    "id",
    "listing_id",
    "title",
    "comuna",
    "property_type",
    "address_label",
    "price_uf",
    "price_clp",
    "estimated_value_uf",
    "estimated_value_clp",
    "m2",
    "bedrooms",
    "bathrooms",
    "parking_spaces",
    "dormitorios",
    "banos",
    "estacionamientos",
    "source",
    "listing_url",
    "detected_at",
    "captured_at",
    "days_on_market",
    "confidence",
    "score",
    "status",
    "tags",
    "short_summary",
    "url",
    "signals",
    "price_history",
    "portal_presence",
}


def test_demo_listings_have_required_fields():
    listings = get_demo_listings()

    assert len(listings) >= 12
    assert {"nunoa", "providencia", "las_condes", "vitacura", "penalolen"} <= {
        item["comuna"] for item in listings
    }
    for item in listings:
        assert set(item) >= REQUIRED_LISTING_FIELDS
        assert item["address_label"]
        assert item["listing_url"].startswith("https://demo.avm.local/")
        assert item["price_clp"] > 0
        assert item["estimated_value_clp"] > 0
        assert item["tags"]
        assert item["short_summary"]


def test_demo_opportunities_have_scores_and_confidence():
    opportunities = get_demo_opportunities()

    assert opportunities
    for item in opportunities:
        assert item["score"] > 0
        assert item["discount_pct"] > 0
        assert item["confidence"] in {"high", "medium", "low"}
        assert item["estimated_price_uf"] >= item["price_uf"]


def test_demo_portfolio_has_movements_and_alerts():
    portfolio = get_demo_portfolio()

    assert portfolio
    for item in portfolio:
        assert "saved_price_uf" in item
        assert "movement_pct" in item
        assert "movement_label" in item
        assert isinstance(item["alerts"], list)


def test_demo_signals_have_minimum_shape():
    signals = []
    for item in get_demo_listings():
        signals.extend(item["signals"])

    assert signals
    for signal in signals:
        assert set(signal) >= {
            "type",
            "signal_type",
            "tone",
            "label",
            "explanation",
            "severity",
            "confidence",
            "suggested_action",
        }
        assert signal["tone"] in {"neutral", "positive", "negative", "warning", "premium"}


def test_demo_price_history_has_valid_events():
    listings = get_demo_listings()

    for item in listings:
        assert item["price_history"]
        for event in item["price_history"]:
            assert set(event) >= {"date", "price_uf", "event"}
            assert event["price_uf"] > 0
            assert event["source"] == "demo_activity_engine"
            assert event["is_demo"] is True
            assert event["event"] in {
                "publicado",
                "rebaja",
                "subida",
                "republicado",
                "sin cambios",
            }


def test_demo_portal_presence_has_valid_contract():
    listings = get_demo_listings()
    all_presence = [presence for item in listings for presence in item["portal_presence"]]

    assert all_presence
    for item in all_presence:
        assert set(item) >= {
            "portal_name",
            "is_active",
            "first_seen",
            "last_seen",
            "price_seen_uf",
            "listing_url",
            "confidence",
        }
        assert item["portal_name"] in {
            "PortalInmobiliario",
            "Yapo",
            "Toctoc",
            "MercadoLibre",
            "ChilePropiedades",
        }


def test_demo_valuation_and_risk_report_are_present():
    valuation = get_demo_valuation_result()
    risk = get_demo_risk_report()
    recommendations = get_demo_recommendations()

    assert valuation["estimated_price_uf"] > 0
    assert valuation["comparables"]
    assert risk["risk_score"] >= 0
    assert risk["signals"]
    assert recommendations["buyer"]
    assert recommendations["owner"]


def test_broker_demo_anchor_examples_stay_stable():
    listings = {item["listing_id"]: item for item in get_demo_listings()}

    assert listings[9101]["comuna"] == "nunoa"
    assert listings[9101]["discount_pct"] > 10
    assert "rebaja reciente" in listings[9101]["tags"]

    assert listings[9102]["comuna"] == "providencia"
    assert listings[9102]["confidence"] == "high"

    assert listings[9104]["comuna"] == "macul"
    assert listings[9104]["price_uf"] < 3500

    assert listings[9109]["confidence"] == "low"
    assert any(signal["type"] == "legal_risk" for signal in listings[9109]["signals"])

    assert listings[9110]["comuna"] == "nunoa"
    assert "comparable" in listings[9110]["tags"]


def test_broker_demo_valuation_has_clear_confidence_and_comparables():
    valuation = get_demo_valuation_result()

    assert valuation["confidence"] == "high"
    assert valuation["comparable_count"] >= 5
    assert len(valuation["comparables"]) >= 3
    assert valuation["warnings"]
