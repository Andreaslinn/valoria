"""Demo-only buyer journey state and thesis generation."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from ui.demo_negotiation import build_demo_negotiation_report
from ui.demo_offer import build_demo_offer_simulation

DEMO_BUYER_JOURNEY_STATE_KEY = "demo_buyer_journey_state"
DEMO_BUYER_PROFILES: dict[str, dict[str, Any]] = {
    "primer_comprador": {
        "label": "Primer comprador",
        "default_budget_uf": 5200,
        "target_communes": ["nunoa", "providencia", "macul"],
        "recommendation_bias": "Priorizar seguridad documental, liquidez y gastos controlados.",
        "risk_focus": ["sobreprecio", "gastos comunes", "documentación incompleta"],
        "strategy_bias": "conservadora",
    },
    "inversionista_inicial": {
        "label": "Inversionista inicial",
        "default_budget_uf": 4300,
        "target_communes": ["santiago", "macul", "nunoa"],
        "recommendation_bias": "Buscar descuento, arriendo potencial y salida futura líquida.",
        "risk_focus": ["vacancia", "liquidez", "riesgo legal simulado"],
        "strategy_bias": "moderada",
    },
    "familia_upgrade": {
        "label": "Familia buscando upgrade",
        "default_budget_uf": 9800,
        "target_communes": ["la_reina", "penalolen", "las_condes"],
        "recommendation_bias": "Balancear ubicación, espacio, riesgo legal y estabilidad de barrio.",
        "risk_focus": ["regularización", "colegios/servicios", "tiempo de mudanza"],
        "strategy_bias": "moderada",
    },
}


def ensure_demo_buyer_journey_state(
    session_state: MutableMapping[str, Any],
    listings: list[dict[str, Any]],
) -> dict[str, Any]:
    state = session_state.get(DEMO_BUYER_JOURNEY_STATE_KEY)
    if _valid_state(state):
        return state
    state = create_demo_buyer_journey_state(listings)
    session_state[DEMO_BUYER_JOURNEY_STATE_KEY] = state
    return state


def create_demo_buyer_journey_state(listings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    profile = "primer_comprador"
    selected = int(listings[0]["listing_id"]) if listings else None
    return {
        "is_demo": True,
        "selected_property": selected,
        "saved_properties": [selected] if selected is not None else [],
        "selected_strategy": DEMO_BUYER_PROFILES[profile]["strategy_bias"],
        "decision_notes": "",
        "offer_strategy": {},
        "buyer_profile": profile,
        "budget_uf": DEMO_BUYER_PROFILES[profile]["default_budget_uf"],
        "target_communes": list(DEMO_BUYER_PROFILES[profile]["target_communes"]),
        "decision_thesis": {},
    }


def set_buyer_profile(state: dict[str, Any], profile: str) -> dict[str, Any]:
    _assert_state(state)
    if profile not in DEMO_BUYER_PROFILES:
        raise ValueError(f"Invalid demo buyer profile: {profile}")
    state["buyer_profile"] = profile
    state["budget_uf"] = DEMO_BUYER_PROFILES[profile]["default_budget_uf"]
    state["target_communes"] = list(DEMO_BUYER_PROFILES[profile]["target_communes"])
    state["selected_strategy"] = DEMO_BUYER_PROFILES[profile]["strategy_bias"]
    return state


def select_journey_property(state: dict[str, Any], property_id: int) -> dict[str, Any]:
    _assert_state(state)
    state["selected_property"] = int(property_id)
    return state


def save_journey_property(state: dict[str, Any], property_id: int) -> dict[str, Any]:
    _assert_state(state)
    property_id = int(property_id)
    if property_id not in state["saved_properties"]:
        state["saved_properties"].append(property_id)
    state["selected_property"] = property_id
    return state


def set_journey_strategy(state: dict[str, Any], strategy: str) -> dict[str, Any]:
    _assert_state(state)
    if strategy not in {"conservadora", "moderada", "agresiva"}:
        raise ValueError(f"Invalid demo journey strategy: {strategy}")
    state["selected_strategy"] = strategy
    return state


def set_journey_notes(state: dict[str, Any], notes: str) -> dict[str, Any]:
    _assert_state(state)
    state["decision_notes"] = notes.strip()
    return state


def set_journey_offer_strategy(state: dict[str, Any], offer_strategy: dict[str, Any]) -> dict[str, Any]:
    _assert_state(state)
    if offer_strategy.get("is_demo") is not True:
        raise ValueError("Demo offer strategy is required.")
    state["offer_strategy"] = dict(offer_strategy)
    state["selected_strategy"] = str(offer_strategy["strategy"])
    return state


def generate_decision_thesis(state: dict[str, Any], listing: dict[str, Any]) -> dict[str, Any]:
    _assert_state(state)
    profile = DEMO_BUYER_PROFILES[state["buyer_profile"]]
    negotiation = build_demo_negotiation_report(listing)
    strategy = state.get("selected_strategy") or negotiation["strategy"]
    saved_offer = state.get("offer_strategy") if isinstance(state.get("offer_strategy"), dict) else {}
    if saved_offer.get("property_id") != int(listing["listing_id"]) or saved_offer.get("strategy") != strategy:
        saved_offer = build_demo_offer_simulation(
            listing,
            buyer_profile=str(state["buyer_profile"]),
            strategy=strategy,
        )
    risks = _risks_for_profile(profile, listing, negotiation)
    thesis = {
        "is_demo": True,
        "property_id": int(listing["listing_id"]),
        "buyer_profile": state["buyer_profile"],
        "profile_label": profile["label"],
        "why_this_property": _why_this_property(profile, listing),
        "main_risks": risks,
        "next_steps": [
            "Abrir Risk Report demo y revisar señales críticas.",
            "Comparar con otra propiedad del mismo rango.",
            "Validar documentos reales antes de cualquier decisión fuera del demo.",
        ],
        "suggested_offer_uf": int(saved_offer["selected_offer_uf"]),
        "offer_acceptance_probability": int(saved_offer["acceptance_probability"]),
        "offer_risk": saved_offer["risk_of_losing_opportunity"],
        "negotiation_argument": saved_offer["negotiation_argument"],
        "selected_strategy": strategy,
        "confidence_level": _confidence_level(listing, negotiation, risks),
        "notes": state.get("decision_notes", ""),
        "disclaimer": "Tesis simulada para Product Lab. No es recomendación financiera, legal ni de inversión.",
    }
    state["decision_thesis"] = thesis
    return thesis


def _why_this_property(profile: dict[str, Any], listing: dict[str, Any]) -> str:
    return (
        f"{listing['title']} calza con {profile['label'].lower()} por precio UF {listing['price_uf']:,}, "
        f"comuna {listing['comuna']} y score demo {listing['score']:.1f}. {profile['recommendation_bias']}"
    ).replace(",", ".")


def _risks_for_profile(profile: dict[str, Any], listing: dict[str, Any], negotiation: dict[str, Any]) -> list[str]:
    risks = list(profile["risk_focus"][:2])
    if listing.get("confidence") == "low":
        risks.append("baja confianza de datos demo")
    if any(signal["tone"] == "negative" for signal in negotiation["signals"]):
        risks.append("señal negativa de negociación demo")
    if listing["price_uf"] > int(DEMO_BUYER_PROFILES["primer_comprador"]["default_budget_uf"]) and profile["label"] == "Primer comprador":
        risks.append("presupuesto exigido para primer comprador")
    return risks[:4]


def _confidence_level(listing: dict[str, Any], negotiation: dict[str, Any], risks: list[str]) -> str:
    if listing.get("confidence") == "high" and negotiation["negotiation_score"] >= 65 and len(risks) <= 2:
        return "alta"
    if listing.get("confidence") == "low" or len(risks) >= 4:
        return "baja"
    return "media"


def _valid_state(value: Any) -> bool:
    return isinstance(value, dict) and value.get("is_demo") is True


def _assert_state(state: dict[str, Any]) -> None:
    if not _valid_state(state):
        raise ValueError("Demo buyer journey state is required.")
