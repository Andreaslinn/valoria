"""Demo-only portfolio state and calculations."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime
from typing import Any, MutableMapping

DEMO_PORTFOLIO_STATE_KEY = "demo_portfolio_state"
DEMO_PORTFOLIO_STATUSES = {"mirando", "contactar", "negociar", "descartada", "favorita"}
DEFAULT_SAVED_AT = "2026-05-08T09:00:00"


def ensure_demo_portfolio_state(
    session_state: MutableMapping[str, Any],
    seed_listings: list[dict[str, Any]],
) -> dict[str, Any]:
    state = session_state.get(DEMO_PORTFOLIO_STATE_KEY)
    if _is_valid_state(state):
        return state
    state = create_demo_portfolio_state(seed_listings)
    session_state[DEMO_PORTFOLIO_STATE_KEY] = state
    return state


def create_demo_portfolio_state(seed_listings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    state: dict[str, Any] = {"is_demo": True, "items": {}}
    for listing in seed_listings or []:
        add_demo_property(state, listing, saved_at=listing.get("saved_at"))
    return state


def add_demo_property(
    state: dict[str, Any],
    listing: dict[str, Any],
    *,
    saved_at: str | None = None,
) -> dict[str, Any]:
    _assert_demo_state(state)
    property_id = _property_id(listing)
    saved_price = int(listing.get("saved_price_uf") or listing.get("price_uf") or 0)
    state["items"][str(property_id)] = {
        "property_id": property_id,
        "saved_at": saved_at or DEFAULT_SAVED_AT,
        "saved_price_uf": saved_price,
        "status": "mirando",
        "favorite": False,
        "note": "",
        "tags": [],
        "is_demo": True,
    }
    return state


def remove_demo_property(state: dict[str, Any], property_id: int) -> dict[str, Any]:
    _assert_demo_state(state)
    state["items"].pop(str(property_id), None)
    return state


def set_demo_property_status(state: dict[str, Any], property_id: int, status: str) -> dict[str, Any]:
    _assert_demo_state(state)
    if status not in DEMO_PORTFOLIO_STATUSES:
        raise ValueError(f"Invalid demo portfolio status: {status}")
    item = _require_item(state, property_id)
    item["status"] = status
    if status == "favorita":
        item["favorite"] = True
    return state


def set_demo_property_favorite(state: dict[str, Any], property_id: int, favorite: bool = True) -> dict[str, Any]:
    _assert_demo_state(state)
    item = _require_item(state, property_id)
    item["favorite"] = favorite
    if favorite:
        item["status"] = "favorita"
    elif item.get("status") == "favorita":
        item["status"] = "mirando"
    return state


def set_demo_property_note(state: dict[str, Any], property_id: int, note: str) -> dict[str, Any]:
    _assert_demo_state(state)
    _require_item(state, property_id)["note"] = note.strip()
    return state


def add_demo_property_tag(state: dict[str, Any], property_id: int, tag: str) -> dict[str, Any]:
    _assert_demo_state(state)
    clean = tag.strip()
    if not clean:
        return state
    item = _require_item(state, property_id)
    tags = item.setdefault("tags", [])
    if clean not in tags:
        tags.append(clean)
    return state


def get_saved_demo_portfolio(
    state: dict[str, Any],
    listings: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    _assert_demo_state(state)
    by_id = {_property_id(listing): listing for listing in listings}
    saved: list[dict[str, Any]] = []
    for raw_id, entry in state["items"].items():
        listing = by_id.get(int(raw_id))
        if listing is None:
            continue
        saved.append(_merge_listing(entry, listing, now=now))
    return sorted(saved, key=lambda item: (item["favorite"], item["score"]), reverse=True)


def calculate_demo_portfolio_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    total_change_uf = sum(int(item.get("change_uf") or 0) for item in items)
    price_drops = sum(1 for item in items if int(item.get("change_uf") or 0) < 0)
    alerts = [alert for item in items for alert in item.get("demo_alerts", [])]
    comuna = Counter(str(item.get("comuna")) for item in items if item.get("comuna")).most_common(1)
    best = max(items, key=lambda item: float(item.get("score") or 0), default=None)
    return {
        "saved_count": len(items),
        "total_change_uf": total_change_uf,
        "price_drop_count": price_drops,
        "active_alert_count": len(alerts),
        "top_comuna": comuna[0][0] if comuna else "Sin datos",
        "best_opportunity": best["title"] if best else "Sin propiedades",
        "is_demo": True,
    }


def _merge_listing(entry: dict[str, Any], listing: dict[str, Any], *, now: datetime | None) -> dict[str, Any]:
    item = deepcopy(listing)
    saved_price = int(entry.get("saved_price_uf") or item.get("price_uf") or 0)
    current_price = int(item.get("price_uf") or 0)
    change_uf = current_price - saved_price
    item.update(
        {
            "saved_at": entry["saved_at"],
            "saved_price_uf": saved_price,
            "saved_price_clp": int(item.get("saved_price_clp") or saved_price * 38_000),
            "change_uf": change_uf,
            "movement_pct": round((change_uf / saved_price) * 100, 1) if saved_price else 0.0,
            "movement_label": "Bajo desde guardado" if change_uf < 0 else "Subio desde guardado" if change_uf > 0 else "Estable",
            "movement_tone": "positive" if change_uf < 0 else "warning" if change_uf > 0 else "neutral",
            "days_since_saved": _days_since(entry["saved_at"], now=now),
            "demo_status": entry["status"],
            "favorite": bool(entry.get("favorite")),
            "note": entry.get("note", ""),
            "local_tags": list(entry.get("tags", [])),
            "demo_alerts": _build_demo_alerts(item, change_uf),
            "is_demo": True,
        }
    )
    item["alerts"] = [alert["label"] for alert in item["demo_alerts"]]
    return item


def _build_demo_alerts(listing: dict[str, Any], change_uf: int) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    signal_types = {signal["signal_type"] for signal in listing.get("signals", [])}
    if change_uf < 0:
        alerts.append({"type": "price_drop", "label": "Bajo de precio", "tone": "positive"})
    if listing.get("signals"):
        alerts.append({"type": "new_signal", "label": "Nueva senal", "tone": "premium"})
    if len(listing.get("portal_presence", [])) > 1:
        alerts.append({"type": "portal_seen", "label": "Aparecio en otro portal", "tone": "premium"})
    if {"price_drop", "seller_pressure", "aggressive_negotiation", "below_market"} & signal_types:
        alerts.append({"type": "negotiation", "label": "Oportunidad de negociacion", "tone": "warning"})
    if "legal_risk" in signal_types:
        alerts.append({"type": "risk", "label": "Riesgo detectado", "tone": "negative"})
    return alerts


def _days_since(saved_at: str, *, now: datetime | None) -> int:
    current = now or datetime.now()
    try:
        saved = datetime.fromisoformat(saved_at.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return 0
    return max((current.replace(tzinfo=None) - saved).days, 0)


def _property_id(listing: dict[str, Any]) -> int:
    return int(listing.get("listing_id") or listing.get("id"))


def _is_valid_state(value: Any) -> bool:
    return isinstance(value, dict) and value.get("is_demo") is True and isinstance(value.get("items"), dict)


def _assert_demo_state(state: dict[str, Any]) -> None:
    if not _is_valid_state(state):
        raise ValueError("Demo portfolio state is required.")


def _require_item(state: dict[str, Any], property_id: int) -> dict[str, Any]:
    item = state["items"].get(str(property_id))
    if item is None:
        raise KeyError(f"Demo property is not saved: {property_id}")
    return item
