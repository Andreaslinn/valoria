"""Demo-only decision board workflow for Product Lab."""
from __future__ import annotations

from collections import Counter
from collections.abc import MutableMapping
from typing import Any

from ui.demo_negotiation import build_demo_negotiation_report

DEMO_DECISION_BOARD_STATE_KEY = "demo_decision_board_state"
DEMO_DECISION_BOARD_STATUSES = {
    "descubierta": "Descubierta",
    "seguimiento": "En seguimiento",
    "contactar": "Contactar",
    "negociar": "Negociar",
    "descartada": "Descartada",
    "favorita": "Favorita",
}
PORTFOLIO_TO_BOARD_STATUS = {
    "mirando": "seguimiento",
    "contactar": "contactar",
    "negociar": "negociar",
    "descartada": "descartada",
    "favorita": "favorita",
}
BOARD_TO_PORTFOLIO_STATUS = {
    "seguimiento": "mirando",
    "contactar": "contactar",
    "negociar": "negociar",
    "descartada": "descartada",
    "favorita": "favorita",
}
DEMO_DECISION_BOARD_DISCLAIMER = (
    "Tablero demo para ordenar decisiones. No es recomendacion financiera ni legal."
)


def ensure_demo_decision_board_state(
    session_state: MutableMapping[str, Any],
    listings: list[dict[str, Any]],
    portfolio_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = session_state.get(DEMO_DECISION_BOARD_STATE_KEY)
    if _is_valid_state(state):
        _seed_missing_properties(state, listings, portfolio_state)
        return state
    state = create_demo_decision_board_state(listings, portfolio_state)
    session_state[DEMO_DECISION_BOARD_STATE_KEY] = state
    return state


def create_demo_decision_board_state(
    listings: list[dict[str, Any]],
    portfolio_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state: dict[str, Any] = {"is_demo": True, "items": {}}
    _seed_missing_properties(state, listings, portfolio_state)
    return state


def move_demo_decision_property(
    state: dict[str, Any],
    property_id: int,
    status: str,
) -> dict[str, Any]:
    _assert_state(state)
    if status not in DEMO_DECISION_BOARD_STATUSES:
        raise ValueError(f"Invalid demo decision status: {status}")
    item = state["items"].setdefault(str(int(property_id)), {"property_id": int(property_id), "is_demo": True})
    item["status"] = status
    return state


def get_demo_decision_board_cards(
    listings: list[dict[str, Any]],
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    _assert_state(state)
    cards = []
    for listing in listings:
        property_id = int(listing["listing_id"])
        board_item = state["items"].get(str(property_id), {})
        status = str(board_item.get("status") or "descubierta")
        negotiation = build_demo_negotiation_report(listing)
        risk_level = _risk_level(listing)
        signal = negotiation["signals"][0]["label"] if negotiation["signals"] else "Seguimiento demo"
        cards.append(
            {
                "is_demo": True,
                "property_id": property_id,
                "status": status,
                "status_label": DEMO_DECISION_BOARD_STATUSES[status],
                "title": listing["title"],
                "price_uf": int(listing["price_uf"]),
                "comuna": listing["comuna"],
                "score": float(listing.get("score") or 0),
                "risk": risk_level,
                "risk_tone": _risk_tone(risk_level),
                "main_signal": signal,
                "next_action": _next_action(status, risk_level, signal),
                "listing": listing,
            }
        )
    return sorted(cards, key=lambda item: (item["status"], -item["score"], item["title"]))


def summarize_demo_decision_board(cards: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(card["status"] for card in cards)
    best = sorted(
        [card for card in cards if card["status"] not in {"descartada"}],
        key=lambda item: item["score"],
        reverse=True,
    )[:3]
    risks_open = sum(1 for card in cards if card["risk"] in {"alto", "medio"} and card["status"] != "descartada")
    pending = sum(1 for card in cards if card["status"] in {"descubierta", "seguimiento", "contactar"})
    return {
        "is_demo": True,
        "counts_by_status": {status: counts.get(status, 0) for status in DEMO_DECISION_BOARD_STATUSES},
        "best_candidates": best,
        "open_risks": risks_open,
        "pending_decisions": pending,
    }


def sync_decision_status_to_portfolio(
    board_status: str,
    portfolio_state: dict[str, Any],
    listing: dict[str, Any],
) -> None:
    if board_status not in BOARD_TO_PORTFOLIO_STATUS:
        return
    property_id = int(listing["listing_id"])
    items = portfolio_state.setdefault("items", {})
    if str(property_id) not in items:
        return
    items[str(property_id)]["status"] = BOARD_TO_PORTFOLIO_STATUS[board_status]
    if board_status == "favorita":
        items[str(property_id)]["favorite"] = True


def _seed_missing_properties(
    state: dict[str, Any],
    listings: list[dict[str, Any]],
    portfolio_state: dict[str, Any] | None,
) -> None:
    portfolio_items = portfolio_state.get("items", {}) if isinstance(portfolio_state, dict) else {}
    for listing in listings:
        property_id = int(listing["listing_id"])
        if str(property_id) in state["items"]:
            continue
        portfolio_status = portfolio_items.get(str(property_id), {}).get("status")
        status = PORTFOLIO_TO_BOARD_STATUS.get(str(portfolio_status), "descubierta")
        state["items"][str(property_id)] = {"property_id": property_id, "status": status, "is_demo": True}


def _next_action(status: str, risk: str, signal: str) -> str:
    if status == "descubierta":
        return "Guardar o revisar checklist antes de avanzar."
    if status == "seguimiento":
        return "Mirar alertas y actividad reciente."
    if status == "contactar":
        return "Preparar preguntas y validar disponibilidad."
    if status == "negociar":
        return "Abrir simulador de oferta y definir rango maximo."
    if status == "favorita":
        return "Completar checklist y comparar con candidatas."
    if status == "descartada":
        return "Mantener solo como referencia de comparables."
    if risk == "alto":
        return "Abrir Risk Report antes de cualquier paso."
    return f"Revisar senal principal: {signal}."


def _risk_level(listing: dict[str, Any]) -> str:
    legal_score = int(listing.get("legal_score") or 80)
    if legal_score < 65 or float(listing.get("discount_pct") or 0) < -4:
        return "alto"
    if legal_score < 75 or str(listing.get("confidence")) == "low":
        return "medio"
    return "bajo"


def _risk_tone(risk: str) -> str:
    if risk == "alto":
        return "negative"
    if risk == "medio":
        return "warning"
    return "positive"


def _is_valid_state(value: Any) -> bool:
    return isinstance(value, dict) and value.get("is_demo") is True and isinstance(value.get("items"), dict)


def _assert_state(state: dict[str, Any]) -> None:
    if not _is_valid_state(state):
        raise ValueError("Demo decision board state is required.")
