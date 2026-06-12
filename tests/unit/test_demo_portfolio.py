from __future__ import annotations

from datetime import datetime

from ui.demo_data import get_demo_listings
from ui.demo_portfolio import (
    DEMO_PORTFOLIO_STATE_KEY,
    add_demo_property,
    add_demo_property_tag,
    calculate_demo_portfolio_metrics,
    create_demo_portfolio_state,
    ensure_demo_portfolio_state,
    get_saved_demo_portfolio,
    remove_demo_property,
    set_demo_property_note,
    set_demo_property_status,
)


def test_can_add_and_remove_demo_property():
    listing = get_demo_listings()[0]
    state = create_demo_portfolio_state()

    add_demo_property(state, listing)
    assert str(listing["listing_id"]) in state["items"]
    assert state["items"][str(listing["listing_id"])]["is_demo"] is True

    remove_demo_property(state, listing["listing_id"])
    assert str(listing["listing_id"]) not in state["items"]


def test_can_change_demo_status():
    listing = get_demo_listings()[0]
    state = create_demo_portfolio_state([listing])

    set_demo_property_status(state, listing["listing_id"], "negociar")

    assert state["items"][str(listing["listing_id"])]["status"] == "negociar"


def test_can_add_demo_note_and_tag():
    listing = get_demo_listings()[0]
    state = create_demo_portfolio_state([listing])

    set_demo_property_note(state, listing["listing_id"], "Llamar al corredor")
    add_demo_property_tag(state, listing["listing_id"], "oferta")

    item = state["items"][str(listing["listing_id"])]
    assert item["note"] == "Llamar al corredor"
    assert item["tags"] == ["oferta"]


def test_demo_variation_is_calculated_from_saved_price():
    listing = {**get_demo_listings()[0], "saved_price_uf": 4520}
    state = create_demo_portfolio_state([listing])
    saved = get_saved_demo_portfolio(state, [listing], now=datetime(2026, 5, 8))
    metrics = calculate_demo_portfolio_metrics(saved)

    assert saved[0]["saved_price_uf"] == 4520
    assert saved[0]["price_uf"] == 4250
    assert saved[0]["change_uf"] == -270
    assert saved[0]["movement_pct"] == -6.0
    assert saved[0]["days_since_saved"] >= 0
    assert metrics["total_change_uf"] == -270
    assert metrics["price_drop_count"] == 1
    assert metrics["active_alert_count"] >= 1


def test_demo_portfolio_state_stays_in_session_mapping_only():
    session: dict[str, object] = {}
    listings = get_demo_listings()[:1]

    state = ensure_demo_portfolio_state(session, listings)

    assert session == {DEMO_PORTFOLIO_STATE_KEY: state}
    assert state["is_demo"] is True
    assert all(item["is_demo"] is True for item in state["items"].values())
