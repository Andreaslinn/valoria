"""Demo-only market context by comuna for Product Lab."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

DEMO_MARKET_CONTEXT_DISCLAIMER = (
    "Contexto de mercado simulado para Product Lab. No representa datos reales de mercado."
)
DEMO_MARKET_BADGES = {
    "Mercado caliente",
    "Mercado equilibrado",
    "Inventario alto",
    "Alta competencia",
    "Buen momento para negociar",
    "Liquidez alta",
    "Liquidez baja",
}

DEMO_MARKET_CONTEXTS: dict[str, dict[str, Any]] = {
    "nunoa": {
        "comuna": "nunoa",
        "label": "Ñuñoa",
        "market_temperature": "caliente",
        "inventory_level": "medio",
        "demand_level": "alta",
        "average_days_on_market": 31,
        "median_price_uf": 4860,
        "median_price_per_m2_uf": 74,
        "active_comparables": 18,
        "recent_price_trend": "estable con rebajas puntuales",
        "liquidity_score": 86,
        "negotiation_pressure": "media",
        "buyer_competition": "alta",
        "short_market_summary": "Ñuñoa combina demanda activa, buena liquidez y oportunidades si aparece rebaja.",
    },
    "providencia": {
        "comuna": "providencia",
        "label": "Providencia",
        "market_temperature": "caliente",
        "inventory_level": "medio",
        "demand_level": "alta",
        "average_days_on_market": 27,
        "median_price_uf": 6250,
        "median_price_per_m2_uf": 83,
        "active_comparables": 16,
        "recent_price_trend": "leve alza",
        "liquidity_score": 90,
        "negotiation_pressure": "baja",
        "buyer_competition": "alta",
        "short_market_summary": "Providencia se mueve rápido; el comprador necesita claridad de precio máximo.",
    },
    "las_condes": {
        "comuna": "las_condes",
        "label": "Las Condes",
        "market_temperature": "equilibrado",
        "inventory_level": "alto",
        "demand_level": "media",
        "average_days_on_market": 54,
        "median_price_uf": 9100,
        "median_price_per_m2_uf": 96,
        "active_comparables": 22,
        "recent_price_trend": "plano",
        "liquidity_score": 64,
        "negotiation_pressure": "media",
        "buyer_competition": "media",
        "short_market_summary": "Las Condes tiene más inventario demo y permite comparar con calma.",
    },
    "la_reina": {
        "comuna": "la_reina",
        "label": "La Reina",
        "market_temperature": "equilibrado",
        "inventory_level": "bajo",
        "demand_level": "media",
        "average_days_on_market": 62,
        "median_price_uf": 9800,
        "median_price_per_m2_uf": 66,
        "active_comparables": 9,
        "recent_price_trend": "rebajas selectivas",
        "liquidity_score": 68,
        "negotiation_pressure": "alta",
        "buyer_competition": "media",
        "short_market_summary": "La Reina premia negociar con paciencia, sobre todo en casas familiares.",
    },
    "macul": {
        "comuna": "macul",
        "label": "Macul",
        "market_temperature": "caliente",
        "inventory_level": "bajo",
        "demand_level": "alta",
        "average_days_on_market": 34,
        "median_price_uf": 3180,
        "median_price_per_m2_uf": 65,
        "active_comparables": 11,
        "recent_price_trend": "demanda sostenida",
        "liquidity_score": 82,
        "negotiation_pressure": "media",
        "buyer_competition": "alta",
        "short_market_summary": "Macul se ve líquido en tickets bajos, con competencia por unidades eficientes.",
    },
    "santiago": {
        "comuna": "santiago",
        "label": "Santiago",
        "market_temperature": "equilibrado",
        "inventory_level": "alto",
        "demand_level": "media",
        "average_days_on_market": 58,
        "median_price_uf": 3120,
        "median_price_per_m2_uf": 61,
        "active_comparables": 28,
        "recent_price_trend": "rebajas frecuentes",
        "liquidity_score": 61,
        "negotiation_pressure": "alta",
        "buyer_competition": "media",
        "short_market_summary": "Santiago ofrece más alternativas demo y mejor espacio para negociar precio.",
    },
    "vitacura": {
        "comuna": "vitacura",
        "label": "Vitacura",
        "market_temperature": "frio",
        "inventory_level": "medio",
        "demand_level": "baja",
        "average_days_on_market": 78,
        "median_price_uf": 11800,
        "median_price_per_m2_uf": 112,
        "active_comparables": 10,
        "recent_price_trend": "lento",
        "liquidity_score": 48,
        "negotiation_pressure": "alta",
        "buyer_competition": "baja",
        "short_market_summary": "Vitacura se comporta como mercado premium lento; conviene exigir margen.",
    },
    "penalolen": {
        "comuna": "penalolen",
        "label": "Peñalolén",
        "market_temperature": "caliente",
        "inventory_level": "bajo",
        "demand_level": "alta",
        "average_days_on_market": 24,
        "median_price_uf": 7200,
        "median_price_per_m2_uf": 60,
        "active_comparables": 8,
        "recent_price_trend": "absorción rápida",
        "liquidity_score": 79,
        "negotiation_pressure": "baja",
        "buyer_competition": "alta",
        "short_market_summary": "Peñalolén muestra baja oferta demo y competencia en productos familiares.",
    },
}


def get_demo_market_context(comuna: str | None, *, demo_mode: bool = True) -> dict[str, Any]:
    if not demo_mode:
        return {}
    key = _normalize_comuna(comuna)
    context = deepcopy(DEMO_MARKET_CONTEXTS.get(key, DEMO_MARKET_CONTEXTS["nunoa"]))
    context["badges"] = _badges_for_context(context)
    context["buyer_meaning"] = _buyer_meaning(context)
    context["owner_meaning"] = _owner_meaning(context)
    context["disclaimer"] = DEMO_MARKET_CONTEXT_DISCLAIMER
    context["is_demo"] = True
    return context


def get_all_demo_market_contexts(*, demo_mode: bool = True) -> dict[str, dict[str, Any]]:
    if not demo_mode:
        return {}
    return {key: get_demo_market_context(key, demo_mode=True) for key in DEMO_MARKET_CONTEXTS}


def _badges_for_context(context: dict[str, Any]) -> list[str]:
    badges: list[str] = []
    if context["market_temperature"] == "caliente":
        badges.append("Mercado caliente")
    else:
        badges.append("Mercado equilibrado")
    if context["inventory_level"] == "alto":
        badges.append("Inventario alto")
    if context["buyer_competition"] == "alta":
        badges.append("Alta competencia")
    if context["negotiation_pressure"] == "alta":
        badges.append("Buen momento para negociar")
    if context["liquidity_score"] >= 78:
        badges.append("Liquidez alta")
    if context["liquidity_score"] <= 55:
        badges.append("Liquidez baja")
    return badges


def _buyer_meaning(context: dict[str, Any]) -> str:
    if context["buyer_competition"] == "alta":
        return "Como comprador, define precio máximo antes de contactar y actúa rápido si el fit es bueno."
    if context["negotiation_pressure"] == "alta":
        return "Como comprador, hay espacio demo para pedir descuento con comparables y permanencia."
    return "Como comprador, conviene comparar alternativas y negociar con disciplina."


def _owner_meaning(context: dict[str, Any]) -> str:
    if context["inventory_level"] == "alto":
        return "Como propietario, el precio inicial debe ser competitivo para destacar entre comparables."
    if context["liquidity_score"] >= 78:
        return "Como propietario, la liquidez demo sugiere buena recepción si el precio está alineado."
    return "Como propietario, puede ser necesario ajustar expectativas o esperar mejor timing."


def _normalize_comuna(value: str | None) -> str:
    raw = (value or "nunoa").strip().lower()
    replacements = {
        "ñ": "n",
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        " ": "_",
    }
    for source, target in replacements.items():
        raw = raw.replace(source, target)
    return raw
