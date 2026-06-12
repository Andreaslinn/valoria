from __future__ import annotations

import pytest

from ui.demo_buyer_journey import (
    DEMO_BUYER_JOURNEY_STATE_KEY,
    DEMO_BUYER_PROFILES,
    create_demo_buyer_journey_state,
    ensure_demo_buyer_journey_state,
    generate_decision_thesis,
    save_journey_property,
    select_journey_property,
    set_buyer_profile,
    set_journey_notes,
    set_journey_offer_strategy,
    set_journey_strategy,
)
from ui.demo_data import get_demo_listings
from ui.demo_offer import build_demo_offer_simulation


def test_buyer_journey_state_initializes():
    listings = get_demo_listings()
    session: dict[str, object] = {}

    state = ensure_demo_buyer_journey_state(session, listings)

    assert session[DEMO_BUYER_JOURNEY_STATE_KEY] is state
    assert state["is_demo"] is True
    assert state["selected_property"] == listings[0]["listing_id"]
    assert state["buyer_profile"] in DEMO_BUYER_PROFILES
    assert state["budget_uf"] > 0
    assert state["target_communes"]


def test_selection_and_save_property_work():
    listings = get_demo_listings()
    state = create_demo_buyer_journey_state(listings)
    property_id = listings[3]["listing_id"]

    select_journey_property(state, property_id)
    save_journey_property(state, property_id)

    assert state["selected_property"] == property_id
    assert property_id in state["saved_properties"]


def test_valid_profiles_change_recommendations():
    listings = get_demo_listings()
    state = create_demo_buyer_journey_state(listings)

    set_buyer_profile(state, "inversionista_inicial")

    assert state["buyer_profile"] == "inversionista_inicial"
    assert state["budget_uf"] == DEMO_BUYER_PROFILES["inversionista_inicial"]["default_budget_uf"]
    assert state["selected_strategy"] == DEMO_BUYER_PROFILES["inversionista_inicial"]["strategy_bias"]


def test_invalid_profile_is_rejected():
    state = create_demo_buyer_journey_state(get_demo_listings())

    with pytest.raises(ValueError):
        set_buyer_profile(state, "fantasma")


def test_decision_thesis_is_generated():
    listing = get_demo_listings()[0]
    state = create_demo_buyer_journey_state([listing])
    set_journey_strategy(state, "moderada")
    set_journey_notes(state, "Me gusta por liquidez, revisar gastos comunes.")

    thesis = generate_decision_thesis(state, listing)

    assert thesis["is_demo"] is True
    assert thesis["property_id"] == listing["listing_id"]
    assert thesis["why_this_property"]
    assert thesis["main_risks"]
    assert thesis["next_steps"]
    assert thesis["suggested_offer_uf"] > 0
    assert 0 <= thesis["offer_acceptance_probability"] <= 100
    assert thesis["offer_risk"] in {"bajo", "medio", "alto"}
    assert thesis["negotiation_argument"]
    assert thesis["confidence_level"] in {"alta", "media", "baja"}
    assert thesis["notes"] == "Me gusta por liquidez, revisar gastos comunes."
    assert state["decision_thesis"] == thesis


def test_invalid_strategy_is_rejected():
    state = create_demo_buyer_journey_state(get_demo_listings())

    with pytest.raises(ValueError):
        set_journey_strategy(state, "azar")


def test_offer_strategy_can_be_saved_in_journey():
    listing = get_demo_listings()[0]
    state = create_demo_buyer_journey_state([listing])
    simulation = build_demo_offer_simulation(
        listing,
        buyer_profile=state["buyer_profile"],
        strategy="agresiva",
    )

    set_journey_offer_strategy(state, simulation)
    thesis = generate_decision_thesis(state, listing)

    assert state["offer_strategy"]["selected_offer_uf"] == simulation["selected_offer_uf"]
    assert thesis["selected_strategy"] == "agresiva"
    assert thesis["suggested_offer_uf"] == simulation["selected_offer_uf"]
