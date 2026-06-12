from __future__ import annotations

from ui.demo_dashboard import build_demo_dashboard
from ui.demo_data import get_demo_listings, get_demo_portfolio
from ui.demo_portfolio import create_demo_portfolio_state, get_saved_demo_portfolio


def test_dashboard_provider_returns_demo_data():
    listings = get_demo_listings()
    state = create_demo_portfolio_state(get_demo_portfolio())
    saved = get_saved_demo_portfolio(state, listings)

    dashboard = build_demo_dashboard(listings, saved)

    assert dashboard["is_demo"] is True
    assert dashboard["summary"]["portfolio_saved"] == len(saved)
    assert dashboard["summary"]["active_opportunities"] > 0
    assert dashboard["summary"]["recent_alerts"] > 0
    assert dashboard["disclaimer"]


def test_dashboard_feeds_are_not_empty():
    listings = get_demo_listings()
    state = create_demo_portfolio_state(get_demo_portfolio())
    saved = get_saved_demo_portfolio(state, listings)
    modules = build_demo_dashboard(listings, saved)["modules"]

    assert modules["watchlist_movers"]
    assert modules["market_movers"]
    assert modules["alert_feed"]
    assert modules["opportunity_feed"]
    assert modules["risk_feed"]
    assert modules["portfolio_health"]["value"]
    assert modules["exposure_by_comuna"]


def test_dashboard_property_references_are_valid():
    listings = get_demo_listings()
    valid_ids = {item["listing_id"] for item in listings}
    state = create_demo_portfolio_state(get_demo_portfolio())
    saved = get_saved_demo_portfolio(state, listings)
    dashboard = build_demo_dashboard(listings, saved)

    assert set(dashboard["property_ids"]) == valid_ids
    for feed_name in ["watchlist_movers", "alert_feed", "opportunity_feed", "risk_feed"]:
        for item in dashboard["modules"][feed_name]:
            assert item["property_id"] in valid_ids
            assert item["value"]
            assert item["interpretation"]
            assert item["suggested_action"]


def test_dashboard_real_mode_is_isolated():
    assert build_demo_dashboard(get_demo_listings(), get_demo_portfolio(), demo_mode=False) == {}
