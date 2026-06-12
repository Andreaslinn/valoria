"""Demo-only personal real-estate dashboard provider."""
from __future__ import annotations

from collections import Counter
from typing import Any

from ui.demo_autofact import build_demo_autofact_report
from ui.demo_market import get_demo_market_context
from ui.demo_negotiation import build_demo_negotiation_report
from ui.demo_portfolio import calculate_demo_portfolio_metrics


def build_demo_dashboard(
    listings: list[dict[str, Any]],
    saved_items: list[dict[str, Any]],
    *,
    demo_mode: bool = True,
) -> dict[str, Any]:
    if not demo_mode:
        return {}
    by_id = {int(item["listing_id"]): item for item in listings}
    saved_ids = {int(item["listing_id"]) for item in saved_items}
    opportunities = sorted(listings, key=lambda item: (float(item.get("discount_pct") or 0), float(item.get("score") or 0)), reverse=True)
    risk_rank = sorted(listings, key=_risk_weight, reverse=True)
    portfolio_metrics = calculate_demo_portfolio_metrics(saved_items)
    dashboard = {
        "is_demo": True,
        "summary": _summary(saved_items, opportunities, risk_rank, portfolio_metrics),
        "modules": {
            "watchlist_movers": _watchlist_movers(saved_items),
            "market_movers": _market_movers(listings),
            "alert_feed": _alert_feed(saved_items, risk_rank),
            "opportunity_feed": _opportunity_feed(opportunities),
            "risk_feed": _risk_feed(risk_rank),
            "portfolio_health": _portfolio_health(saved_items, portfolio_metrics),
            "exposure_by_comuna": _exposure_by_comuna(saved_items),
        },
        "actions": {
            "saved_property_ids": sorted(saved_ids),
            "available_property_ids": sorted(set(by_id) - saved_ids),
        },
        "property_ids": sorted(by_id),
        "disclaimer": "Dashboard Lab con datos simulados. No representa mercado real ni recomendaciones reales.",
    }
    return dashboard


def _summary(
    saved_items: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
    risk_rank: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    observed_comunas = sorted({item["comuna"] for item in saved_items})
    active_alerts = sum(len(item.get("demo_alerts", [])) for item in saved_items)
    return {
        "portfolio_saved": len(saved_items),
        "total_variation_uf": metrics["total_change_uf"],
        "active_opportunities": len([item for item in opportunities if float(item.get("discount_pct") or 0) > 2.5]),
        "recent_alerts": active_alerts,
        "observed_comunas": len(observed_comunas),
        "best_opportunity": _ref(opportunities[0], "Revisar precio y señales antes de contactar."),
        "highest_risk_property": _ref(risk_rank[0], "Abrir Risk Report y Autofact demo antes de ofertar."),
        "recent_movements": len(_watchlist_movers(saved_items)),
    }


def _watchlist_movers(saved_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    movers = sorted(saved_items, key=lambda item: abs(int(item.get("change_uf") or 0)), reverse=True)
    return [
        _card(
            item,
            f"{_format_change(item.get('change_uf'))} desde guardado",
            "El precio simulado se movió desde que lo agregaste.",
            "Abrir propiedad o ajustar estado en Portafolio demo.",
            "positive" if int(item.get("change_uf") or 0) < 0 else "warning",
        )
        for item in movers[:4]
    ]


def _market_movers(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contexts = {item["comuna"]: get_demo_market_context(item["comuna"]) for item in listings}
    ranked = sorted(contexts.values(), key=lambda item: (item["liquidity_score"], item["active_comparables"]), reverse=True)
    return [
        {
            "property_id": None,
            "title": context["label"],
            "value": f"{context['liquidity_score']}/100 liquidez",
            "interpretation": context["short_market_summary"],
            "suggested_action": context["buyer_meaning"],
            "tone": "positive" if context["liquidity_score"] >= 78 else "warning",
        }
        for context in ranked[:4]
    ]


def _alert_feed(saved_items: list[dict[str, Any]], risk_rank: list[dict[str, Any]]) -> list[dict[str, Any]]:
    feed: list[dict[str, Any]] = []
    for item in saved_items:
        for alert in item.get("demo_alerts", [])[:2]:
            feed.append(_card(item, alert["label"], "Alerta simulada conectada a tu watchlist.", "Ver Risk Report demo.", alert.get("tone", "warning")))
    for item in risk_rank[:2]:
        feed.append(_card(item, "Riesgo legal simulado", "Autofact demo sugiere revisión documental.", "Abrir Autofact demo.", "negative"))
    return feed[:6]


def _opportunity_feed(opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _card(
            item,
            f"{item['discount_pct']}% bajo estimación",
            "Oportunidad demo priorizada por descuento y score.",
            "Guardar en watchlist o abrir Risk Report demo.",
            "positive" if float(item.get("discount_pct") or 0) >= 8 else "warning",
        )
        for item in opportunities[:5]
    ]


def _risk_feed(risk_rank: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _card(
            item,
            f"Riesgo {build_demo_autofact_report(item, _base_autofact(item))['risk_level']}",
            "Flags legales simuladas requieren revisión.",
            "Abrir Autofact demo antes de negociar.",
            "negative" if _risk_weight(item) >= 3 else "warning",
        )
        for item in risk_rank[:4]
    ]


def _portfolio_health(saved_items: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
    risk_count = sum(1 for item in saved_items if any(signal["signal_type"] == "legal_risk" for signal in item.get("signals", [])))
    favorite_count = sum(1 for item in saved_items if item.get("favorite"))
    return {
        "value": f"{metrics['saved_count']} guardadas",
        "interpretation": f"{metrics['price_drop_count']} con rebaja, {risk_count} con riesgo simulado, {favorite_count} favoritas.",
        "suggested_action": "Priorizar propiedades con rebaja y bajo riesgo demo.",
        "tone": "positive" if risk_count == 0 else "warning",
        "property_id": saved_items[0]["listing_id"] if saved_items else None,
    }


def _exposure_by_comuna(saved_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(item["comuna"] for item in saved_items)
    return [
        {
            "property_id": None,
            "title": get_demo_market_context(comuna)["label"],
            "value": f"{count} propiedades",
            "interpretation": "Exposición demo concentrada en esta comuna.",
            "suggested_action": "Comparar liquidez, inventario y riesgo por comuna.",
            "tone": "premium" if count >= 2 else "neutral",
        }
        for comuna, count in counts.most_common()
    ]


def _card(item: dict[str, Any], value: str, interpretation: str, action: str, tone: str) -> dict[str, Any]:
    return {
        "property_id": int(item["listing_id"]),
        "title": item["title"],
        "value": value,
        "interpretation": interpretation,
        "suggested_action": action,
        "tone": tone,
    }


def _ref(item: dict[str, Any], action: str) -> dict[str, Any]:
    return _card(item, f"Score {item['score']:.1f}", item["short_summary"], action, "premium")


def _risk_weight(item: dict[str, Any]) -> int:
    signal_types = {signal["signal_type"] for signal in item.get("signals", [])}
    weight = 0
    if "legal_risk" in signal_types:
        weight += 4
    if float(item.get("score") or 0) < 55:
        weight += 2
    if item.get("confidence") == "low":
        weight += 3
    return weight


def _base_autofact(item: dict[str, Any]) -> dict[str, Any]:
    high = "legal_risk" in {signal["signal_type"] for signal in item.get("signals", [])}
    return {
        "legal_score": 48 if high else 76,
        "cbr_status": "CBR simulado: antecedente por revisar" if high else "CBR simulado: sin alertas críticas",
        "ownership_flags": ["Dominio vigente simulado"],
        "liens": ["Hipoteca simulada por confirmar"] if high else [],
        "debt_flags": [],
        "tax_warning": "Revisar deuda fiscal simulada" if high else None,
        "permits_warning": None,
        "liquidity_score": int(min(max(float(item.get("score") or 70), 40), 92)),
        "market_score": int(min(max(float(item.get("score") or 70), 40), 92)),
        "risk_level": "high" if high else "medium",
        "confidence": item.get("confidence", "medium"),
        "disclaimer": "Datos simulados.",
    }


def _format_change(value: Any) -> str:
    number = int(value or 0)
    sign = "+" if number > 0 else ""
    return f"{sign}UF {number:,}".replace(",", ".")
