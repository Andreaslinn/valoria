from __future__ import annotations

import pytest

from ui.demo_data import get_demo_listings
from ui.demo_owner_journey import (
    DEMO_OWNER_JOURNEY_STATE_KEY,
    DEMO_OWNER_SCENARIOS,
    build_owner_journey_report,
    create_demo_owner_journey_state,
    ensure_demo_owner_journey_state,
    select_owner_property,
    set_owner_scenario,
)


def test_owner_journey_state_initializes():
    listings = get_demo_listings()
    session: dict[str, object] = {}

    state = ensure_demo_owner_journey_state(session, listings)

    assert session[DEMO_OWNER_JOURNEY_STATE_KEY] is state
    assert state["is_demo"] is True
    assert state["selected_property"] == listings[0]["listing_id"]
    assert state["selected_scenario"] in DEMO_OWNER_SCENARIOS


def test_owner_property_selection_and_scenario_work():
    listings = get_demo_listings()
    state = create_demo_owner_journey_state(listings)

    select_owner_property(state, listings[2]["listing_id"])
    set_owner_scenario(state, "arrendar")

    assert state["selected_property"] == listings[2]["listing_id"]
    assert state["selected_scenario"] == "arrendar"


def test_invalid_owner_scenario_is_rejected():
    state = create_demo_owner_journey_state(get_demo_listings())

    with pytest.raises(ValueError):
        set_owner_scenario(state, "comprar_castillo")


def test_owner_report_has_valid_scenarios_and_numbers():
    listing = get_demo_listings()[0]
    report = build_owner_journey_report(listing)
    simulator = report["simulator"]

    assert report["is_demo"] is True
    assert report["property_id"] == listing["listing_id"]
    assert report["estimated_value_uf"] > 0
    assert report["liquidity"] >= 0
    assert report["demand"] in {"baja", "media", "alta"}
    assert report["competition"] in {"baja", "media", "alta"}
    assert report["wait_risk"] in {"bajo", "medio", "alto"}
    assert report["rental_potential"] in {"bajo", "medio", "alto"}
    assert simulator["sell_now_price_uf"] > 0
    assert simulator["wait_price_uf"] > 0
    assert simulator["annual_rent_income_uf"] > 0
    assert simulator["simulated_costs_uf"] >= 0
    assert simulator["sensitivity"]["downside_uf"] < simulator["sensitivity"]["upside_uf"]


def test_owner_recommendations_are_complete():
    report = build_owner_journey_report(get_demo_listings()[0])

    assert {item["scenario"] for item in report["recommendations"]} == DEMO_OWNER_SCENARIOS
    for item in report["recommendations"]:
        assert item["pros"]
        assert item["contras"]
        assert item["assumptions"]
        assert item["risk"] in {"bajo", "medio", "alto"}
        assert item["demo_confidence"] in {"media", "alta"}


def test_owner_report_real_mode_is_isolated():
    assert build_owner_journey_report(get_demo_listings()[0], demo_mode=False) == {}
