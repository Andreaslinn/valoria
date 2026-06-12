from __future__ import annotations

import pytest

from ui.demo_data import get_demo_listings, get_demo_portfolio
from ui.demo_decision_board import (
    DEMO_DECISION_BOARD_STATUSES,
    create_demo_decision_board_state,
    ensure_demo_decision_board_state,
    get_demo_decision_board_cards,
    move_demo_decision_property,
    summarize_demo_decision_board,
    sync_decision_status_to_portfolio,
)
from ui.demo_portfolio import create_demo_portfolio_state


def test_decision_board_initializes_with_valid_statuses() -> None:
    listings = get_demo_listings()
    session: dict[str, object] = {}
    portfolio = create_demo_portfolio_state(get_demo_portfolio())

    state = ensure_demo_decision_board_state(session, listings, portfolio)
    cards = get_demo_decision_board_cards(listings, state)

    assert state["is_demo"] is True
    assert cards
    assert {card["status"] for card in cards}.issubset(DEMO_DECISION_BOARD_STATUSES)
    assert all(card["next_action"] for card in cards)


def test_move_property_between_columns() -> None:
    listing = get_demo_listings()[0]
    state = create_demo_decision_board_state([listing])

    move_demo_decision_property(state, int(listing["listing_id"]), "negociar")

    assert state["items"][str(listing["listing_id"])]["status"] == "negociar"


def test_decision_board_summary_counts() -> None:
    listings = get_demo_listings()[:3]
    state = create_demo_decision_board_state(listings)
    move_demo_decision_property(state, int(listings[0]["listing_id"]), "favorita")
    move_demo_decision_property(state, int(listings[1]["listing_id"]), "descartada")
    cards = get_demo_decision_board_cards(listings, state)

    summary = summarize_demo_decision_board(cards)

    assert summary["is_demo"] is True
    assert summary["counts_by_status"]["favorita"] == 1
    assert summary["counts_by_status"]["descartada"] == 1
    assert summary["pending_decisions"] >= 1
    assert summary["best_candidates"]


def test_decision_board_syncs_to_portfolio_status() -> None:
    listing = get_demo_portfolio()[0]
    portfolio = create_demo_portfolio_state([listing])

    sync_decision_status_to_portfolio("favorita", portfolio, listing)

    item = portfolio["items"][str(listing["listing_id"])]
    assert item["status"] == "favorita"
    assert item["favorite"] is True


def test_invalid_decision_status_is_rejected() -> None:
    listing = get_demo_listings()[0]
    state = create_demo_decision_board_state([listing])

    with pytest.raises(ValueError):
        move_demo_decision_property(state, int(listing["listing_id"]), "perdida")
