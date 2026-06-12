from __future__ import annotations

from ui.demo_data import get_demo_listings
from ui.demo_offer import build_demo_offer_simulation
from ui.demo_providers import get_demo_risk_report


def test_offer_strategies_generate_distinct_values() -> None:
    listing = get_demo_listings()[0]

    conservative = build_demo_offer_simulation(listing, buyer_profile="primer_comprador", strategy="conservadora")
    moderate = build_demo_offer_simulation(listing, buyer_profile="primer_comprador", strategy="moderada")
    aggressive = build_demo_offer_simulation(listing, buyer_profile="primer_comprador", strategy="agresiva")

    assert conservative["suggested_offer_uf"] > moderate["suggested_offer_uf"] > aggressive["suggested_offer_uf"]


def test_offer_probability_is_bounded_and_offer_positive() -> None:
    listing = get_demo_listings()[1]
    simulation = build_demo_offer_simulation(
        listing,
        buyer_profile="inversionista_inicial",
        strategy="agresiva",
        manual_offer_uf=1,
    )

    assert simulation["selected_offer_uf"] > 0
    assert 0 <= simulation["acceptance_probability"] <= 100
    assert simulation["risk_of_losing_opportunity"] in {"bajo", "medio", "alto"}


def test_manual_offer_changes_feedback_and_probability() -> None:
    listing = get_demo_listings()[2]
    high_offer = build_demo_offer_simulation(
        listing,
        buyer_profile="familia_upgrade",
        strategy="moderada",
        manual_offer_uf=int(listing["price_uf"] * 0.99),
    )
    low_offer = build_demo_offer_simulation(
        listing,
        buyer_profile="familia_upgrade",
        strategy="moderada",
        manual_offer_uf=int(listing["price_uf"] * 0.88),
    )

    assert high_offer["acceptance_probability"] > low_offer["acceptance_probability"]
    assert high_offer["feedback"] != low_offer["feedback"]


def test_offer_integrates_risk_report_read() -> None:
    listing = get_demo_listings()[0]
    report = get_demo_risk_report(int(listing["listing_id"]), demo_mode=True)

    simulation = build_demo_offer_simulation(
        listing,
        buyer_profile="primer_comprador",
        strategy="moderada",
        risk_report=report,
    )

    assert simulation["risk_report_read"]["label"]
    assert simulation["risk_report_read"]["message"]


def test_offer_engine_is_demo_only() -> None:
    listing = get_demo_listings()[0]

    assert build_demo_offer_simulation(
        listing,
        buyer_profile="primer_comprador",
        strategy="moderada",
        demo_mode=False,
    ) == {}
