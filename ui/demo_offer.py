"""Demo-only offer simulation heuristics for Product Lab."""
from __future__ import annotations

from typing import Any

from ui.demo_negotiation import build_demo_negotiation_report

DEMO_OFFER_DISCLAIMER = (
    "Simulador demo para Product Lab. No es recomendacion financiera, legal ni de inversion."
)
DEMO_OFFER_STRATEGIES = {"conservadora", "moderada", "agresiva"}


def build_demo_offer_simulation(
    listing: dict[str, Any],
    *,
    buyer_profile: str,
    strategy: str,
    manual_offer_uf: int | None = None,
    risk_report: dict[str, Any] | None = None,
    demo_mode: bool = True,
) -> dict[str, Any]:
    if not demo_mode:
        return {}
    if strategy not in DEMO_OFFER_STRATEGIES:
        raise ValueError(f"Invalid demo offer strategy: {strategy}")

    negotiation = build_demo_negotiation_report(listing, demo_mode=True)
    inputs = negotiation["inputs"]
    price = int(inputs["published_price_uf"])
    estimated = int(inputs["estimated_price_uf"])
    suggested = _suggested_offer(price, inputs, strategy)
    offer = max(int(manual_offer_uf if manual_offer_uf is not None else suggested), 1)
    discount_vs_price = _pct(price - offer, price)
    difference_vs_estimate = _pct(estimated - offer, estimated)
    acceptance = _acceptance_probability(offer, price, inputs, risk_report)
    loss_risk, loss_tone = _loss_risk(acceptance, inputs)
    risk_read = _risk_read(strategy, risk_report)

    return {
        "is_demo": True,
        "property_id": int(listing["listing_id"]),
        "buyer_profile": buyer_profile,
        "strategy": strategy,
        "published_price_uf": price,
        "estimated_value_uf": estimated,
        "suggested_offer_uf": suggested,
        "selected_offer_uf": offer,
        "manual_offer_uf": manual_offer_uf,
        "discount_vs_price_pct": round(discount_vs_price, 1),
        "difference_vs_estimate_pct": round(difference_vs_estimate, 1),
        "acceptance_probability": acceptance,
        "risk_of_losing_opportunity": loss_risk,
        "risk_tone": loss_tone,
        "negotiation_argument": _argument(listing, inputs, negotiation["signals"], strategy),
        "next_steps": _next_steps(strategy, risk_read),
        "feedback": _feedback(offer, suggested, acceptance, loss_risk),
        "risk_report_read": risk_read,
        "evidence": _evidence(inputs),
        "disclaimer": DEMO_OFFER_DISCLAIMER,
    }


def _suggested_offer(price: int, inputs: dict[str, Any], strategy: str) -> int:
    base_discount = {"conservadora": 1.2, "moderada": 3.5, "agresiva": 6.5}[strategy]
    flexibility = 0.0
    flexibility += min(int(inputs["price_drops_count"]), 3) * 0.7
    if int(inputs["days_on_market"]) >= 60:
        flexibility += 1.0
    elif int(inputs["days_on_market"]) >= 35:
        flexibility += 0.5
    if float(inputs["discount_vs_estimate_pct"]) >= 8:
        flexibility += 0.6

    competition = 0.0
    if int(inputs["portal_presence_count"]) >= 3:
        competition += 0.6
    if int(inputs["liquidity_score"]) >= 80:
        competition += 0.4

    discount = max(base_discount + flexibility - competition, 0)
    return max(round(price * (1 - discount / 100)), 1)


def _acceptance_probability(
    offer: int,
    price: int,
    inputs: dict[str, Any],
    risk_report: dict[str, Any] | None,
) -> int:
    discount = _pct(price - offer, price)
    probability = 62.0
    probability -= max(discount - 2.0, 0) * 5.2
    probability += min(int(inputs["days_on_market"]), 90) * 0.16
    probability += int(inputs["price_drops_count"]) * 7.0
    probability += max(float(inputs["total_price_drop_pct"]), 0) * 0.8
    probability -= int(inputs["portal_presence_count"]) * 2.5
    probability -= max(int(inputs["liquidity_score"]) - 65, 0) * 0.18
    if inputs["market_pressure"] == "alta":
        probability += 4
    elif inputs["market_pressure"] == "baja":
        probability -= 4
    if risk_report:
        probability -= max(70 - int(risk_report.get("scores", {}).get("total", 70)), 0) * 0.12
    return int(min(max(round(probability), 5), 95))


def _loss_risk(acceptance: int, inputs: dict[str, Any]) -> tuple[str, str]:
    if acceptance < 35:
        return "alto", "negative"
    if acceptance < 60 or int(inputs["portal_presence_count"]) >= 3:
        return "medio", "warning"
    return "bajo", "positive"


def _risk_read(strategy: str, risk_report: dict[str, Any] | None) -> dict[str, Any]:
    if not risk_report:
        return {
            "label": "Riesgo no evaluado",
            "tone": "neutral",
            "message": "Abre Risk Report Demo para cruzar la oferta con riesgo simulado.",
        }
    scores = risk_report.get("scores", {})
    total = int(scores.get("total", 70))
    legal = int(scores.get("legal_simulated", 70))
    if strategy == "agresiva" and (total < 68 or legal < 65):
        return {
            "label": "Estrategia mas riesgosa",
            "tone": "warning",
            "message": "La oferta agresiva se cruza con riesgos demo que conviene revisar antes de avanzar.",
        }
    if strategy == "conservadora" and total >= 72:
        return {
            "label": "Estrategia defensiva",
            "tone": "positive",
            "message": "El Risk Report Demo permite una postura ordenada sin tensionar demasiado la oportunidad.",
        }
    return {
        "label": "Riesgo balanceado",
        "tone": "premium",
        "message": "La estrategia parece consistente con el perfil de riesgo simulado.",
    }


def _argument(
    listing: dict[str, Any],
    inputs: dict[str, Any],
    signals: list[dict[str, Any]],
    strategy: str,
) -> str:
    labels = [signal["label"].lower() for signal in signals[:2]]
    signal_text = ", ".join(labels) if labels else "seguimiento demo"
    return (
        f"Usar una postura {strategy} apoyada en {signal_text}: la propiedad lleva "
        f"{inputs['days_on_market']} dias publicada, registra {inputs['price_drops_count']} rebaja(s) "
        f"y aparece en {inputs['portal_presence_count']} portal(es) demo."
    )


def _next_steps(strategy: str, risk_read: dict[str, Any]) -> list[str]:
    steps = [
        "Comparar la oferta con el valor estimado demo y el precio publicado.",
        "Revisar actividad, rebajas y presencia multiportal antes de contactar.",
        "Validar antecedentes reales fuera del Lab antes de cualquier decision.",
    ]
    if strategy == "agresiva":
        steps.insert(1, "Preparar un argumento claro para justificar el descuento.")
    if risk_read["tone"] == "warning":
        steps.insert(0, "Revisar Risk Report Demo antes de guardar la tesis.")
    return steps


def _feedback(offer: int, suggested: int, acceptance: int, loss_risk: str) -> str:
    delta_pct = _pct(offer - suggested, suggested)
    if delta_pct <= -4:
        return f"Oferta bastante bajo la sugerencia demo: sube el riesgo a {loss_risk} y la aceptacion queda en {acceptance}%."
    if delta_pct >= 4:
        return f"Oferta sobre la sugerencia demo: mejora aceptacion a {acceptance}%, pero reduce margen negociado."
    return f"Oferta cerca de la sugerencia demo: balance razonable con aceptacion {acceptance}% y riesgo {loss_risk}."


def _evidence(inputs: dict[str, Any]) -> list[str]:
    return [
        f"{inputs['days_on_market']} dias en mercado",
        f"{inputs['price_drops_count']} rebaja(s) detectada(s)",
        f"{inputs['portal_presence_count']} portal(es) demo",
        f"Liquidez demo {inputs['liquidity_score']}/100",
        f"Presion de mercado {inputs['market_pressure']}",
    ]


def _pct(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return (numerator / denominator) * 100
