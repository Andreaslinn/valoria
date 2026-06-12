"""Demo-only owner journey scenarios and simulator."""
from __future__ import annotations

from typing import Any, MutableMapping

from ui.demo_market import get_demo_market_context

DEMO_OWNER_JOURNEY_STATE_KEY = "demo_owner_journey_state"
DEMO_OWNER_SCENARIOS = {"vender_ahora", "esperar_3_6_meses", "arrendar", "preparar_venta"}
DEMO_OWNER_DISCLAIMER = "Simulación demo. No es recomendación financiera real."


def ensure_demo_owner_journey_state(
    session_state: MutableMapping[str, Any],
    listings: list[dict[str, Any]],
) -> dict[str, Any]:
    state = session_state.get(DEMO_OWNER_JOURNEY_STATE_KEY)
    if _valid_state(state):
        return state
    state = create_demo_owner_journey_state(listings)
    session_state[DEMO_OWNER_JOURNEY_STATE_KEY] = state
    return state


def create_demo_owner_journey_state(listings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    selected = int(listings[0]["listing_id"]) if listings else None
    return {
        "is_demo": True,
        "selected_property": selected,
        "selected_scenario": "vender_ahora",
        "improvement_budget_uf": 120,
        "rent_yield_pct": 4.2,
        "holding_months": 6,
    }


def select_owner_property(state: dict[str, Any], property_id: int) -> dict[str, Any]:
    _assert_state(state)
    state["selected_property"] = int(property_id)
    return state


def set_owner_scenario(state: dict[str, Any], scenario: str) -> dict[str, Any]:
    _assert_state(state)
    if scenario not in DEMO_OWNER_SCENARIOS:
        raise ValueError(f"Invalid demo owner scenario: {scenario}")
    state["selected_scenario"] = scenario
    return state


def build_owner_journey_report(
    listing: dict[str, Any],
    *,
    improvement_budget_uf: int = 120,
    rent_yield_pct: float = 4.2,
    holding_months: int = 6,
    demo_mode: bool = True,
) -> dict[str, Any]:
    if not demo_mode:
        return {}
    market = get_demo_market_context(listing["comuna"], demo_mode=True)
    simulator = _simulate(listing, market, improvement_budget_uf, rent_yield_pct, holding_months)
    recommendations = _recommendations(listing, market, simulator)
    return {
        "is_demo": True,
        "property_id": int(listing["listing_id"]),
        "property_title": listing["title"],
        "estimated_value_uf": int(listing["estimated_value_uf"]),
        "market_context": market,
        "liquidity": market["liquidity_score"],
        "demand": market["demand_level"],
        "competition": market["buyer_competition"],
        "wait_risk": _wait_risk(market),
        "rental_potential": _rental_potential(listing, rent_yield_pct),
        "simulator": simulator,
        "recommendations": recommendations,
        "disclaimer": DEMO_OWNER_DISCLAIMER,
    }


def _simulate(
    listing: dict[str, Any],
    market: dict[str, Any],
    improvement_budget_uf: int,
    rent_yield_pct: float,
    holding_months: int,
) -> dict[str, Any]:
    estimated = int(listing["estimated_value_uf"])
    liquidity_bonus = (int(market["liquidity_score"]) - 65) / 100
    trend_bonus = 0.025 if market["market_temperature"] == "caliente" else -0.01 if market["market_temperature"] == "frio" else 0.01
    wait_factor = max(min(trend_bonus + liquidity_bonus * 0.03, 0.06), -0.04)
    sell_now = round(estimated * (0.985 if market["negotiation_pressure"] == "alta" else 1.0))
    wait_price = round(estimated * (1 + wait_factor))
    annual_rent = round(estimated * (rent_yield_pct / 100))
    simulated_costs = round(improvement_budget_uf + estimated * 0.012 + holding_months * 8)
    sensitivity = {
        "downside_uf": round(wait_price * 0.97 - simulated_costs),
        "base_uf": round(wait_price - simulated_costs),
        "upside_uf": round(wait_price * 1.04 - simulated_costs),
    }
    return {
        "sell_now_price_uf": sell_now,
        "wait_price_uf": wait_price,
        "annual_rent_income_uf": annual_rent,
        "simulated_costs_uf": simulated_costs,
        "improvement_budget_uf": improvement_budget_uf,
        "rent_yield_pct": rent_yield_pct,
        "holding_months": holding_months,
        "sensitivity": sensitivity,
    }


def _recommendations(listing: dict[str, Any], market: dict[str, Any], simulator: dict[str, Any]) -> list[dict[str, Any]]:
    hot = market["liquidity_score"] >= 78
    high_pressure = market["negotiation_pressure"] == "alta"
    rental = simulator["annual_rent_income_uf"]
    return [
        {
            "scenario": "vender_ahora",
            "label": "Vender ahora",
            "pros": ["Captura liquidez actual", "Reduce riesgo de espera", "Aprovecha demanda demo"] if hot else ["Evita costos de espera", "Simplifica decisión"],
            "contras": ["Puede dejar upside si el mercado mejora", "Exige precio competitivo"],
            "assumptions": [f"Liquidez demo {market['liquidity_score']}/100", f"Valor estimado UF {listing['estimated_value_uf']}"],
            "risk": "medio" if high_pressure else "bajo",
            "demo_confidence": "alta" if hot else "media",
        },
        {
            "scenario": "esperar_3_6_meses",
            "label": "Esperar 3–6 meses",
            "pros": ["Puede mejorar precio esperado", "Permite observar inventario"],
            "contras": ["Mantiene exposición a mercado", "Puede aumentar competencia"],
            "assumptions": [f"Precio esperado UF {simulator['wait_price_uf']}", f"{simulator['holding_months']} meses de espera"],
            "risk": _wait_risk(market),
            "demo_confidence": "media",
        },
        {
            "scenario": "arrendar",
            "label": "Arrendar",
            "pros": [f"Ingreso anual simulado UF {rental}", "Mantiene opción de venta futura"],
            "contras": ["Riesgo de vacancia", "Gestión de arriendo y mantención"],
            "assumptions": [f"Yield demo {simulator['rent_yield_pct']}%", "Vacancia no modelada en detalle"],
            "risk": "medio",
            "demo_confidence": "media",
        },
        {
            "scenario": "preparar_venta",
            "label": "Preparar venta",
            "pros": ["Mejora presentación", "Puede reducir objeciones de comprador"],
            "contras": ["Requiere costo previo", "No garantiza mayor precio"],
            "assumptions": [f"Mejoras simuladas UF {simulator['improvement_budget_uf']}", "Impacto comercial estimado"],
            "risk": "bajo" if not high_pressure else "medio",
            "demo_confidence": "media",
        },
    ]


def _wait_risk(market: dict[str, Any]) -> str:
    if market["market_temperature"] == "frio" or market["inventory_level"] == "alto":
        return "alto"
    if market["negotiation_pressure"] == "alta":
        return "medio"
    return "bajo"


def _rental_potential(listing: dict[str, Any], rent_yield_pct: float) -> str:
    if listing["property_type"] == "departamento" and rent_yield_pct >= 4:
        return "alto"
    if rent_yield_pct >= 3.5:
        return "medio"
    return "bajo"


def _valid_state(value: Any) -> bool:
    return isinstance(value, dict) and value.get("is_demo") is True


def _assert_state(state: dict[str, Any]) -> None:
    if not _valid_state(state):
        raise ValueError("Demo owner journey state is required.")
