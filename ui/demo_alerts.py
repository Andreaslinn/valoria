"""Demo-only alert center provider for Product Lab."""
from __future__ import annotations

from collections.abc import MutableMapping
from copy import deepcopy
from typing import Any

from ui.demo_market import get_demo_market_context
from ui.demo_negotiation import build_demo_negotiation_report

DEMO_ALERT_STATE_KEY = "demo_alert_center_state"
DEMO_ALERT_CATEGORIES = {
    "precio",
    "oportunidad",
    "riesgo",
    "portal",
    "negociacion",
    "mercado",
    "actividad",
    "comparable",
}
DEMO_ALERT_SEVERITIES = {"info", "warning", "critical", "positive"}
DEMO_ALERT_DISCLAIMER = "Alertas simuladas para Product Lab. No son avisos reales ni recomendaciones."


def build_demo_alerts(listings: list[dict[str, Any]], *, demo_mode: bool = True) -> list[dict[str, Any]]:
    if not demo_mode:
        return []
    alerts: list[dict[str, Any]] = []
    for listing in listings:
        property_id = int(listing["listing_id"])
        alerts.extend(_property_alerts(listing, property_id))
    alerts.extend(_market_alerts(listings))
    return sorted(alerts, key=lambda item: item["created_at"], reverse=True)


def ensure_demo_alert_state(
    session_state: MutableMapping[str, Any],
    alerts: list[dict[str, Any]],
) -> dict[str, Any]:
    _ = alerts
    state = session_state.get(DEMO_ALERT_STATE_KEY)
    if isinstance(state, dict) and state.get("is_demo") is True:
        state.setdefault("read_alert_ids", [])
        return state
    state = {"is_demo": True, "read_alert_ids": []}
    session_state[DEMO_ALERT_STATE_KEY] = state
    return state


def mark_demo_alert_read(state: dict[str, Any], alert_id: str) -> dict[str, Any]:
    _assert_state(state)
    if alert_id not in state["read_alert_ids"]:
        state["read_alert_ids"].append(alert_id)
    return state


def with_demo_alert_read_state(alerts: list[dict[str, Any]], state: dict[str, Any]) -> list[dict[str, Any]]:
    _assert_state(state)
    read_ids = set(state["read_alert_ids"])
    hydrated = []
    for alert in alerts:
        item = deepcopy(alert)
        item["is_read"] = item["id"] in read_ids
        hydrated.append(item)
    return hydrated


def filter_demo_alerts(
    alerts: list[dict[str, Any]],
    *,
    category: str | None = None,
    severity: str | None = None,
    unread_only: bool = False,
) -> list[dict[str, Any]]:
    result = []
    for alert in alerts:
        if category and alert["category"] != category:
            continue
        if severity and alert["severity"] != severity:
            continue
        if unread_only and alert.get("is_read"):
            continue
        result.append(alert)
    return result


def _property_alerts(listing: dict[str, Any], property_id: int) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    history = listing.get("price_history", [])
    drops = [item for item in history if item.get("event") == "rebaja"]
    portals = listing.get("portal_presence", [])
    negotiation = build_demo_negotiation_report(listing)

    if drops:
        last_drop = drops[-1]
        alerts.append(_alert(
            f"price-drop-{property_id}",
            property_id,
            "Propiedad bajo de precio",
            f"{listing['title']} registra una rebaja simulada hasta UF {last_drop['price_uf']:,}.".replace(",", "."),
            "positive",
            "precio",
            "2026-05-07T09:10:00",
            "Ver propiedad",
            {"type": "property", "property_id": property_id},
        ))
    if len(portals) >= 2:
        alerts.append(_alert(
            f"portal-{property_id}",
            property_id,
            "Aparecio en otro portal",
            f"Detectamos presencia simulada en {len(portals)} portales. Puede indicar mayor exposicion.",
            "info",
            "portal",
            "2026-05-07T08:25:00",
            "Ver presencia",
            {"type": "property", "property_id": property_id, "section": "portal_presence"},
        ))
    if int(listing.get("days_on_market") or 0) >= 60:
        alerts.append(_alert(
            f"stale-{property_id}",
            property_id,
            "Demasiado tiempo publicada",
            f"Lleva {listing['days_on_market']} dias en mercado demo. Puede ser senal de negociacion.",
            "warning",
            "actividad",
            "2026-05-06T16:45:00",
            "Abrir report",
            {"type": "risk_report", "property_id": property_id},
        ))
    if float(listing.get("discount_pct") or 0) < 0:
        alerts.append(_alert(
            f"overprice-{property_id}",
            property_id,
            "Alerta de sobreprecio",
            "El precio publicado supera el valor estimado demo. Revisa comparables antes de avanzar.",
            "critical",
            "riesgo",
            "2026-05-06T11:35:00",
            "Abrir report",
            {"type": "risk_report", "property_id": property_id},
        ))
    if any(signal["label"] == "Posible vendedor flexible" for signal in negotiation["signals"]):
        alerts.append(_alert(
            f"flexible-{property_id}",
            property_id,
            "Vendedor parece mas flexible",
            "Las senales demo combinan permanencia, rebajas o presion de mercado.",
            "positive",
            "negociacion",
            "2026-05-05T18:20:00",
            "Simular oferta",
            {"type": "decision_board", "property_id": property_id},
        ))
    if int(listing.get("legal_score") or 100) < 70:
        alerts.append(_alert(
            f"legal-{property_id}",
            property_id,
            "Riesgo legal simulado detectado",
            "El Autofact Demo sugiere revisar banderas legales simuladas antes de ofertar.",
            "critical",
            "riesgo",
            "2026-05-05T10:05:00",
            "Abrir report",
            {"type": "risk_report", "property_id": property_id},
        ))
    if float(listing.get("discount_pct") or 0) >= 8:
        alerts.append(_alert(
            f"similar-{property_id}",
            property_id,
            "Nueva oportunidad similar",
            "Aparecio una propiedad demo comparable con brecha atractiva en el radar.",
            "positive",
            "oportunidad",
            "2026-05-04T14:00:00",
            "Ver propiedad",
            {"type": "property", "property_id": property_id},
        ))
    if int(listing.get("score") or 0) >= 75:
        alerts.append(_alert(
            f"comparable-{property_id}",
            property_id,
            "Nueva comparable relevante",
            "El Risk Report Demo puede contrastar esta propiedad con comparables activos.",
            "info",
            "comparable",
            "2026-05-04T09:30:00",
            "Abrir report",
            {"type": "risk_report", "property_id": property_id},
        ))
    return alerts


def _market_alerts(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alerts = []
    seen = set()
    for listing in listings:
        comuna = str(listing.get("comuna") or "").strip()
        if not comuna or comuna in seen:
            continue
        seen.add(comuna)
        context = get_demo_market_context(comuna, demo_mode=True)
        if context and context.get("negotiation_pressure") in {"alta", "media"}:
            alerts.append(_alert(
                f"market-{comuna.lower().replace(' ', '-')}",
                None,
                f"Mercado de {comuna} cambio",
                context["short_market_summary"],
                "warning" if context["negotiation_pressure"] == "alta" else "info",
                "mercado",
                "2026-05-07T07:40:00",
                "Ver mercado",
                {"type": "market_context", "comuna": comuna},
            ))
    return alerts


def _alert(
    alert_id: str,
    property_id: int | None,
    title: str,
    body: str,
    severity: str,
    category: str,
    created_at: str,
    action_label: str,
    action_target: dict[str, Any],
) -> dict[str, Any]:
    if severity not in DEMO_ALERT_SEVERITIES:
        raise ValueError(f"Invalid demo alert severity: {severity}")
    if category not in DEMO_ALERT_CATEGORIES:
        raise ValueError(f"Invalid demo alert category: {category}")
    return {
        "id": alert_id,
        "property_id": property_id,
        "title": title,
        "body": body,
        "severity": severity,
        "category": category,
        "created_at": created_at,
        "action_label": action_label,
        "action_target": action_target,
        "is_demo": True,
    }


def _assert_state(state: dict[str, Any]) -> None:
    if not isinstance(state, dict) or state.get("is_demo") is not True:
        raise ValueError("Demo alert state is required.")
