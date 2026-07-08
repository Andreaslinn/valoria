from __future__ import annotations

import json

from domain.portfolio.contracts import (
    PortfolioState,
    unavailable_avm_state,
    unavailable_compared_state,
    unavailable_delta_state,
    unavailable_favorite_state,
    unavailable_history_state,
    unavailable_recommendation_state,
    unavailable_trend_state,
    unavailable_upside_state,
)


def test_unavailable_portfolio_states_have_machine_readable_reasons() -> None:
    assert unavailable_avm_state().to_payload() == {
        "status": PortfolioState.NEEDS_SNAPSHOT.value,
        "reason": "needs_portfolio_avm_snapshot",
        "available": False,
        "estimated_value_uf": None,
        "estimated_value_clp": None,
        "lower_bound_uf": None,
        "upper_bound_uf": None,
        "confidence": None,
        "snapshot_id": None,
        "snapshot_created_at": None,
    }
    assert unavailable_delta_state().reason == "needs_current_valuation"
    assert unavailable_trend_state().reason == "needs_repeated_avm_snapshots"
    assert unavailable_upside_state().reason == "needs_portfolio_avm_snapshot"
    assert unavailable_history_state().reason == "needs_repeated_avm_snapshots"
    assert unavailable_compared_state().reason == "needs_compared_event_model"
    assert unavailable_favorite_state().reason == "needs_favorites_model"
    assert unavailable_recommendation_state().reason == "portfolio_recommendation_engine_not_implemented"


def test_contract_payloads_are_json_serializable() -> None:
    payload = {
        "avm": unavailable_avm_state().to_payload(),
        "delta": unavailable_delta_state().to_payload(),
        "trend": unavailable_trend_state().to_payload(),
        "upside": unavailable_upside_state().to_payload(),
        "history": unavailable_history_state().to_payload(),
        "compared": unavailable_compared_state().to_payload(),
        "favorites": unavailable_favorite_state().to_payload(),
        "recommendations": unavailable_recommendation_state().to_payload(),
    }

    encoded = json.dumps(payload)

    assert "needs_portfolio_avm_snapshot" in encoded
    assert "portfolio_recommendation_engine_not_implemented" in encoded
