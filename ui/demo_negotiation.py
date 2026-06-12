"""Demo-only negotiation signal heuristics for Product Lab."""
from __future__ import annotations

from typing import Any

DEMO_NEGOTIATION_DISCLAIMER = (
    "Señales simuladas para explorar experiencia futura. No son recomendación financiera, legal ni de inversión."
)
DEMO_NEGOTIATION_STRATEGIES = {"conservadora", "moderada", "agresiva"}


def build_demo_negotiation_report(listing: dict[str, Any], *, demo_mode: bool = True) -> dict[str, Any]:
    if not demo_mode:
        return {}
    inputs = _build_inputs(listing)
    signals = _build_signals(inputs)
    score = _score(inputs)
    strategy = _strategy(score, inputs)
    return {
        "is_demo": True,
        "property_id": int(listing["listing_id"]),
        "inputs": inputs,
        "signals": signals,
        "negotiation_score": score,
        "strategy": strategy,
        "suggested_strategy": _strategy_section(listing, score, strategy),
        "disclaimer": DEMO_NEGOTIATION_DISCLAIMER,
    }


def _build_inputs(listing: dict[str, Any]) -> dict[str, Any]:
    history = listing.get("price_history", [])
    drops = [item for item in history if item.get("event") == "rebaja"]
    first_price = int(history[0]["price_uf"]) if history else int(listing["price_uf"])
    current_price = int(listing["price_uf"])
    total_drop_pct = round(((first_price - current_price) / first_price) * 100, 1) if first_price else 0.0
    discount_vs_estimate_pct = float(listing.get("discount_pct") or 0)
    portal_presence_count = len(listing.get("portal_presence", []))
    activity_level = _activity_level(listing, len(drops), portal_presence_count)
    liquidity_score = int(min(max(float(listing.get("score") or 0), 0), 100))
    return {
        "days_on_market": int(listing.get("days_on_market") or 0),
        "price_drops_count": len(drops),
        "total_price_drop_pct": total_drop_pct,
        "discount_vs_estimate_pct": discount_vs_estimate_pct,
        "portal_presence_count": portal_presence_count,
        "activity_level": activity_level,
        "liquidity_score": liquidity_score,
        "market_pressure": _market_pressure(listing, len(drops)),
        "published_price_uf": current_price,
        "estimated_price_uf": int(listing.get("estimated_value_uf") or current_price),
    }


def _build_signals(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    if inputs["price_drops_count"] >= 2 or inputs["days_on_market"] >= 45:
        signals.append(_signal("Posible vendedor flexible", "warning", "high", "Hay permanencia relevante o rebajas acumuladas.", [
            f"{inputs['days_on_market']} días en mercado",
            f"{inputs['price_drops_count']} rebajas detectadas",
        ], "Preparar oferta con comparables y margen explícito."))
    if inputs["price_drops_count"] >= 1:
        signals.append(_signal("Rebaja reciente", "positive", "high", "El historial demo registra al menos una baja de precio.", [
            f"Caída acumulada {inputs['total_price_drop_pct']}%",
        ], "Contactar usando la rebaja como punto de entrada."))
    if inputs["discount_vs_estimate_pct"] >= 8 and inputs["market_pressure"] in {"media", "alta"}:
        signals.append(_signal("Buen candidato para negociación agresiva", "positive", "medium", "Combina descuento vs estimación con presión de mercado.", [
            f"Descuento vs estimación {inputs['discount_vs_estimate_pct']}%",
            f"Presión de mercado {inputs['market_pressure']}",
        ], "Probar oferta agresiva solo dentro del escenario demo."))
    if inputs["days_on_market"] >= 60:
        signals.append(_signal("Listing estancado", "warning", "medium", "La publicación lleva demasiados días activa para el dataset demo.", [
            f"{inputs['days_on_market']} días publicada",
        ], "Pedir contexto de urgencia y validar si sigue disponible."))
    if inputs["discount_vs_estimate_pct"] >= 5:
        signals.append(_signal("Precio bajo mercado", "positive", "medium", "El precio publicado queda bajo la estimación demo.", [
            f"Brecha estimada {inputs['discount_vs_estimate_pct']}%",
        ], "Priorizar revisión documental antes de ofertar."))
    if inputs["portal_presence_count"] >= 3 or inputs["activity_level"] == "alta":
        signals.append(_signal("Alta competencia en la comuna", "premium", "medium", "La propiedad aparece en varias fuentes o muestra actividad alta.", [
            f"{inputs['portal_presence_count']} portales demo",
            f"Actividad {inputs['activity_level']}",
        ], "Contactar rápido y definir precio máximo antes de negociar."))
    if 0 <= inputs["discount_vs_estimate_pct"] < 3:
        signals.append(_signal("Margen estrecho", "neutral", "medium", "La brecha contra estimación demo es limitada.", [
            f"Brecha estimada {inputs['discount_vs_estimate_pct']}%",
        ], "Evitar sobreofertar; negociar con disciplina."))
    if inputs["discount_vs_estimate_pct"] < 0:
        signals.append(_signal("Riesgo de sobreprecio", "negative", "high", "El precio publicado supera la estimación demo.", [
            f"Brecha negativa {inputs['discount_vs_estimate_pct']}%",
        ], "Esperar rebaja o pedir justificación con comparables."))
    if inputs["liquidity_score"] >= 75 and inputs["market_pressure"] != "alta":
        signals.append(_signal("Buen momento para contactar", "positive", "medium", "Liquidez sana sin presión extrema en el escenario demo.", [
            f"Liquidez demo {inputs['liquidity_score']}/100",
            f"Presión {inputs['market_pressure']}",
        ], "Contactar y pedir antecedentes antes de que aumente competencia."))
    return signals or [
        _signal("Señal de seguimiento", "neutral", "low", "No hay gatillos fuertes, pero conviene monitorear cambios.", [
            f"Actividad {inputs['activity_level']}",
        ], "Mantener en observación demo.")
    ]


def _score(inputs: dict[str, Any]) -> int:
    score = 35
    score += min(inputs["days_on_market"], 90) * 0.18
    score += inputs["price_drops_count"] * 10
    score += max(inputs["total_price_drop_pct"], 0) * 1.2
    score += max(inputs["discount_vs_estimate_pct"], 0) * 1.5
    score += min(inputs["portal_presence_count"], 4) * 3
    score += (inputs["liquidity_score"] - 50) * 0.2
    if inputs["market_pressure"] == "alta":
        score += 8
    elif inputs["market_pressure"] == "baja":
        score -= 6
    if inputs["discount_vs_estimate_pct"] < 0:
        score -= 20
    return int(min(max(round(score), 0), 100))


def _strategy(score: int, inputs: dict[str, Any]) -> str:
    if score >= 75 and inputs["discount_vs_estimate_pct"] >= 5:
        return "agresiva"
    if score >= 50:
        return "moderada"
    return "conservadora"


def _strategy_section(listing: dict[str, Any], score: int, strategy: str) -> dict[str, Any]:
    price = int(listing["price_uf"])
    estimated = int(listing.get("estimated_value_uf") or price)
    if strategy == "agresiva":
        conservative_pct, moderate_pct, aggressive_pct = 2.0, 5.0, 8.0
        loss_risk = "medio-alto"
    elif strategy == "moderada":
        conservative_pct, moderate_pct, aggressive_pct = 1.0, 3.5, 6.0
        loss_risk = "medio"
    else:
        conservative_pct, moderate_pct, aggressive_pct = 0.0, 1.5, 3.0
        loss_risk = "bajo" if score < 40 else "medio"
    return {
        "strategy": strategy,
        "conservative_offer_uf": round(price * (1 - conservative_pct / 100)),
        "moderate_offer_uf": round(price * (1 - moderate_pct / 100)),
        "aggressive_offer_uf": round(price * (1 - aggressive_pct / 100)),
        "estimated_range_uf": [round(min(price, estimated) * 0.94), round(max(price, estimated) * 1.02)],
        "risk_of_losing_opportunity": loss_risk,
        "explanation": f"Estrategia {strategy} derivada de score demo {score}/100 y señales heurísticas.",
        "disclaimer": DEMO_NEGOTIATION_DISCLAIMER,
    }


def _signal(label: str, tone: str, confidence: str, explanation: str, evidence: list[str], suggested_action: str) -> dict[str, Any]:
    return {
        "label": label,
        "explanation": explanation,
        "evidence": evidence,
        "confidence": confidence,
        "severity": tone,
        "tone": tone,
        "suggested_action": suggested_action,
        "disclaimer": DEMO_NEGOTIATION_DISCLAIMER,
        "is_demo": True,
    }


def _activity_level(listing: dict[str, Any], drops_count: int, portal_count: int) -> str:
    if drops_count >= 2 or portal_count >= 3 or listing.get("days_on_market", 0) >= 60:
        return "alta"
    if drops_count == 1 or portal_count == 2:
        return "media"
    return "baja"


def _market_pressure(listing: dict[str, Any], drops_count: int) -> str:
    if listing.get("days_on_market", 0) >= 60 or drops_count >= 2:
        return "alta"
    if listing.get("days_on_market", 0) >= 30 or drops_count == 1:
        return "media"
    return "baja"
