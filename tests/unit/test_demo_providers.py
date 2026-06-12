from __future__ import annotations

from copy import deepcopy

import ui.demo_providers as demo_providers
from ui.demo_data import get_demo_listings
from ui.demo_market import DEMO_MARKET_BADGES, get_all_demo_market_contexts, get_demo_market_context
from ui.demo_providers import (
    DEMO_ACTIVITY_EVENT_TYPES,
    DEMO_ACTIVITY_TONES,
    get_demo_autofact_report,
    get_demo_avm_score,
    get_demo_negotiation_report,
    get_demo_negotiation_signals,
    get_demo_owner_recommendations,
    get_demo_portal_presence,
    get_demo_price_history,
    get_demo_property_activity,
    get_demo_property_comparison,
    get_demo_risk_report,
)


def _demo_listing(listing_id: int, *, price_uf: int, m2: float = 50.0) -> dict:
    return {
        "id": listing_id,
        "listing_id": listing_id,
        "title": f"Demo {listing_id}",
        "comuna": "nunoa",
        "price_uf": price_uf,
        "m2": m2,
        "bedrooms": 2,
        "bathrooms": 2,
        "parking_spaces": 1,
        "source": "demo",
        "status": "active",
        "detected_at": "2026-05-01T10:00:00",
    }


def test_demo_avm_score_returns_expected_keys():
    report = get_demo_avm_score(get_demo_listings()[0])

    assert set(report) == {
        "estimated_value_uf",
        "estimated_value_clp",
        "confidence_score",
        "confidence_label",
        "discount_pct",
        "comparables_used",
        "avm_source",
        "is_demo",
    }
    assert report["avm_source"] == "domain_logic_demo"
    assert report["is_demo"] is True


def test_demo_avm_score_does_not_mutate_demo_listings():
    before = get_demo_listings()
    snapshot = deepcopy(before)

    get_demo_avm_score(before[0])

    assert before == snapshot
    assert get_demo_listings() == snapshot


def test_demo_avm_score_excludes_target_from_comparables(monkeypatch):
    target = _demo_listing(1, price_uf=100)
    c1 = _demo_listing(2, price_uf=200)
    c2 = _demo_listing(3, price_uf=200)
    monkeypatch.setattr(demo_providers, "DEMO_LISTINGS", [target, c1, c2])

    report = get_demo_avm_score(target)

    assert report["comparables_used"] == 2


def test_demo_avm_score_handles_insufficient_comparables(monkeypatch):
    target = _demo_listing(1, price_uf=100)
    c1 = _demo_listing(2, price_uf=200)
    monkeypatch.setattr(demo_providers, "DEMO_LISTINGS", [target, c1])

    report = get_demo_avm_score(target)

    assert report["estimated_value_uf"] is None
    assert report["estimated_value_clp"] is None
    assert report["confidence_score"] is None
    assert report["confidence_label"] == "insufficient_demo_comparables"
    assert report["discount_pct"] is None
    assert report["comparables_used"] == 0


def test_demo_avm_score_handles_missing_price_or_m2_safely(monkeypatch):
    missing_price = {**_demo_listing(1, price_uf=100), "price_uf": None}
    missing_m2 = {**_demo_listing(2, price_uf=200), "m2": None}
    monkeypatch.setattr(demo_providers, "DEMO_LISTINGS", [missing_price, missing_m2])

    report = get_demo_avm_score(missing_price)

    assert report["confidence_label"] == "insufficient_demo_comparables"
    assert report["discount_pct"] is None


def test_demo_avm_score_calculates_discount_pct(monkeypatch):
    target = _demo_listing(1, price_uf=100)
    c1 = _demo_listing(2, price_uf=200)
    c2 = _demo_listing(3, price_uf=200)
    monkeypatch.setattr(demo_providers, "DEMO_LISTINGS", [target, c1, c2])

    report = get_demo_avm_score(target)

    assert report["estimated_value_uf"] == 200.0
    assert report["discount_pct"] == 50.0


def test_autofact_provider_has_minimum_contract():
    report = get_demo_autofact_report()

    assert report["is_demo"] is True
    assert report["legal_score"] >= 0
    assert "cbr_status" in report
    assert report["simulated_cbr_status"]
    assert report["property_identity"]
    assert report["ownership_summary"]
    assert report["ownership_history"]
    assert isinstance(report["debt_flags"], list)
    assert report["liquidity_score"] >= 0
    assert report["market_score"] >= 0
    assert report["risk_level"] in {"low", "medium", "high"}
    assert report["disclaimer"]
    assert report["disclaimers"]


def test_portal_presence_provider_has_portal_contract():
    presence = get_demo_portal_presence()

    assert presence
    for item in presence:
        assert set(item) >= {
            "portal_name",
            "is_active",
            "first_seen",
            "last_seen",
            "price_seen_uf",
            "listing_url",
            "confidence",
        }


def test_negotiation_signals_have_actionable_contract():
    signals = get_demo_negotiation_signals()

    assert signals
    for signal in signals:
        assert set(signal) >= {
            "label",
            "explanation",
            "evidence",
            "suggested_action",
            "confidence",
            "severity",
            "tone",
            "disclaimer",
            "is_demo",
        }
        assert signal["evidence"]
        assert signal["is_demo"] is True


def test_owner_recommendations_cover_expected_decisions():
    recommendations = get_demo_owner_recommendations()

    assert {item["recommendation"] for item in recommendations} >= {
        "sell_now",
        "wait",
        "rent",
    }


def test_risk_price_history_and_comparison_providers_are_present():
    risk = get_demo_risk_report()
    history = get_demo_price_history()
    comparison = get_demo_property_comparison()

    assert risk["risk_score"] >= 0
    assert risk["executive_summary"]
    assert risk["market_score"] >= 0
    assert risk["liquidity_score"] >= 0
    assert risk["legal_score"] >= 0
    assert risk["data_quality_score"] >= 0
    assert risk["main_risks"]
    assert risk["main_opportunities"]
    assert risk["recommendation"]
    assert risk["disclaimer"]
    assert len(history) >= 2
    assert {"date", "price_uf", "event"} <= set(history[0])
    assert comparison
    assert {"liquidity_score", "legal_score", "market_score"} <= set(comparison[0])


def test_property_activity_provider_returns_valid_demo_events():
    events = get_demo_property_activity(9101)

    assert len(events) >= 3
    for event in events:
        assert set(event) >= {
            "id",
            "property_id",
            "date",
            "event_type",
            "title",
            "description",
            "severity",
            "tone",
            "source",
            "is_demo",
        }
        assert event["property_id"] == 9101
        assert event["event_type"] in DEMO_ACTIVITY_EVENT_TYPES
        assert event["tone"] in DEMO_ACTIVITY_TONES
        assert event["source"] == "demo_activity_engine"
        assert event["is_demo"] is True


def test_each_important_demo_property_has_activity_history():
    important_ids = [item["listing_id"] for item in get_demo_listings() if item["score"] >= 60]

    assert important_ids
    for property_id in important_ids:
        assert len(get_demo_property_activity(property_id)) >= 3


def test_real_mode_does_not_consume_demo_activity():
    assert get_demo_property_activity(9101, demo_mode=False) == []


def test_risk_report_demo_has_complete_sections():
    report = get_demo_risk_report(9101)

    assert report["is_demo"] is True
    assert report["property_id"] == 9101
    assert report["executive_summary"]
    assert set(report["scores"]) >= {"total", "market", "liquidity", "legal_simulated", "data_quality"}
    assert report["signals"]
    assert report["main_risks"]
    assert report["main_opportunities"]
    assert report["timeline"]
    assert report["price_history"]
    assert report["comparables"]
    assert report["comuna_context"]
    assert report["portal_presence"]
    assert report["recommendation"]
    assert report["demo_disclaimer"]
    assert set(report["sections"]) >= {
        "executive_summary",
        "legal",
        "market",
        "negotiation",
        "timeline",
        "price_history",
        "comparables",
        "comuna_context",
        "portal_presence",
    }


def test_risk_report_demo_sections_have_minimum_data():
    report = get_demo_risk_report(9109)
    legal = report["legal_simulation"]
    market = report["market_section"]
    negotiation = report["negotiation_section"]

    assert legal["cbr_status"]
    assert legal["simulated_liens"]
    assert legal["simulated_prohibitions"]
    assert legal["simulated_contribution_debt"]
    assert legal["permits_regularization"]
    assert legal["disclaimer"]
    assert market["published_price_uf"] > 0
    assert market["estimated_price_uf"] > 0
    assert "supply_pressure" in market
    assert "simulated_demand" in market
    assert market["active_comparables"] > 0
    assert negotiation["suggested_margin_pct"] > 0
    assert negotiation["conservative_strategy"]["offer_uf"] > 0
    assert negotiation["moderate_strategy"]["offer_uf"] > 0
    assert negotiation["aggressive_strategy"]["offer_uf"] > 0
    assert negotiation["explanation"]


def test_risk_report_demo_exists_for_several_properties():
    for property_id in [9101, 9102, 9105, 9109, 9112]:
        report = get_demo_risk_report(property_id)
        assert report["property_id"] == property_id
        assert report["is_demo"] is True
        assert len(report["timeline"]) >= 3
        assert len(report["comparables"]) >= 3


def test_real_mode_does_not_return_demo_risk_report():
    assert get_demo_risk_report(9101, demo_mode=False) == {}


def test_negotiation_report_generates_demo_signals_and_score():
    report = get_demo_negotiation_report(9101)

    assert report["is_demo"] is True
    assert report["signals"]
    assert 0 <= report["negotiation_score"] <= 100
    assert report["strategy"] in {"conservadora", "moderada", "agresiva"}
    assert report["suggested_strategy"]["conservative_offer_uf"] > 0
    assert report["suggested_strategy"]["moderate_offer_uf"] > 0
    assert report["suggested_strategy"]["aggressive_offer_uf"] > 0
    assert report["suggested_strategy"]["estimated_range_uf"][0] > 0
    for signal in report["signals"]:
        assert signal["label"]
        assert signal["explanation"]
        assert signal["evidence"]
        assert signal["suggested_action"]
        assert signal["disclaimer"]


def test_negotiation_report_exists_for_demo_properties():
    for property_id in [9101, 9103, 9105, 9109, 9114]:
        report = get_demo_negotiation_report(property_id)
        assert report["property_id"] == property_id
        assert report["signals"]
        assert 0 <= report["negotiation_score"] <= 100
        assert report["strategy"] in {"conservadora", "moderada", "agresiva"}


def test_real_mode_does_not_return_demo_negotiation_report():
    assert get_demo_negotiation_report(9101, demo_mode=False) == {}


def test_all_demo_comunas_have_market_context():
    contexts = get_all_demo_market_contexts()

    assert set(contexts) == {
        "nunoa",
        "providencia",
        "las_condes",
        "la_reina",
        "macul",
        "santiago",
        "vitacura",
        "penalolen",
    }
    for context in contexts.values():
        assert context["is_demo"] is True
        assert context["short_market_summary"]
        assert context["buyer_meaning"]
        assert context["owner_meaning"]
        assert context["badges"]
        assert set(context["badges"]) <= DEMO_MARKET_BADGES


def test_market_context_metrics_are_in_valid_ranges():
    for context in get_all_demo_market_contexts().values():
        assert context["market_temperature"] in {"caliente", "equilibrado", "frio"}
        assert context["inventory_level"] in {"bajo", "medio", "alto"}
        assert context["demand_level"] in {"baja", "media", "alta"}
        assert 0 < context["average_days_on_market"] <= 180
        assert context["median_price_uf"] > 0
        assert context["median_price_per_m2_uf"] > 0
        assert context["active_comparables"] > 0
        assert 0 <= context["liquidity_score"] <= 100
        assert context["negotiation_pressure"] in {"baja", "media", "alta"}
        assert context["buyer_competition"] in {"baja", "media", "alta"}


def test_risk_report_includes_demo_market_context():
    report = get_demo_risk_report(9101)

    assert report["market_context"]["label"] == "Ñuñoa"
    assert report["sections"]["market_context"]["is_demo"] is True


def test_real_mode_does_not_return_demo_market_context():
    assert get_demo_market_context("nunoa", demo_mode=False) == {}
    assert get_all_demo_market_contexts(demo_mode=False) == {}


def test_autofact_demo_exists_for_demo_properties():
    for property_id in [9101, 9102, 9105, 9109, 9112]:
        report = get_demo_autofact_report(property_id)
        assert report["property_id"] == property_id
        assert report["is_demo"] is True
        assert 0 <= report["legal_score"] <= 100
        assert report["data_confidence"] in {"low", "medium", "high"}
        assert report["legal_timeline"]
        assert report["review_recommendations"]


def test_autofact_flags_have_severity():
    report = get_demo_autofact_report(9109)
    flag_groups = [
        "liens_flags",
        "mortgage_flags",
        "prohibition_flags",
        "tax_flags",
        "permits_flags",
        "municipal_flags",
        "critical_flags",
    ]

    for group in flag_groups:
        assert report[group]
        for flag in report[group]:
            assert flag["label"]
            assert flag["severity"] in {"low", "medium", "high"}


def test_autofact_demo_disclaimers_are_visible_in_contract():
    report = get_demo_autofact_report(9101)

    assert "Datos simulados" in report["disclaimer"]
    assert "No reemplaza estudio de títulos" in report["disclaimer"]
    assert "No usar para decisiones reales" in report["disclaimer"]


def test_risk_report_includes_autofact_demo():
    report = get_demo_risk_report(9101)

    assert report["autofact_report"]["is_demo"] is True
    assert report["sections"]["autofact_report"]["property_id"] == 9101


def test_real_mode_does_not_return_demo_autofact():
    assert get_demo_autofact_report(9101, demo_mode=False) == {}
