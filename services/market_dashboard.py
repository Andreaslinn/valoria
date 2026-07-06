"""Lightweight dashboard contracts for market intelligence placeholders."""
from __future__ import annotations

from typing import Any


def market_briefing_placeholder() -> dict[str, Any]:
    """Return an honest market briefing contract without synthetic metrics."""
    return {
        "status": "coming_soon",
        "available": False,
        "market": "Santiago, Chile",
        "headline": "Briefing de mercado en preparacion",
        "summary": (
            "Se activara cuando exista contrato real de mercado, liquidez y tendencia."
        ),
        "indicators": [
            {
                "key": "supply",
                "label": "Oferta en mercado",
                "status": "coming_soon",
                "value": None,
                "delta_pct": None,
                "unit": None,
                "description": "Requiere contrato de oferta.",
            },
            {
                "key": "time_to_sell",
                "label": "Tiempo de venta",
                "status": "coming_soon",
                "value": None,
                "delta_pct": None,
                "unit": "days",
                "description": "Requiere datos de ciclo de publicacion.",
            },
            {
                "key": "opportunities",
                "label": "Oportunidades",
                "status": "manual",
                "value": None,
                "delta_pct": None,
                "unit": None,
                "description": "Radar se ejecuta bajo demanda.",
            },
        ],
        "insight": {
            "status": "coming_soon",
            "text": (
                "Sin metricas simuladas: Valoria mostrara insights cuando existan "
                "senales publicables."
            ),
        },
        "valoria_index": valoria_index_placeholder(),
        "updated_at": None,
        "source": "valoria_market_contract_placeholder",
    }


def valoria_index_placeholder() -> dict[str, Any]:
    return {
        "status": "coming_soon",
        "available": False,
        "value": None,
        "max": 100,
        "label": "Indice Valoria",
        "confidence_label": "Esperando contrato",
        "description": (
            "Esperando contrato de mercado para publicar una senal agregada."
        ),
        "source": "valoria_index_contract_placeholder",
    }


def microzones_summary_placeholder() -> dict[str, Any]:
    return {
        "status": "coming_soon",
        "available": False,
        "items": [],
        "message": (
            "Microzonas en preparacion. Se activara cuando exista senal de "
            "microzona publicable para el dashboard."
        ),
        "source": "microzone_contract_placeholder",
    }


def liquidity_summary_placeholder() -> dict[str, Any]:
    return {
        "status": "coming_soon",
        "available": False,
        "value": None,
        "max": 100,
        "label": "Liquidez del mercado",
        "message": "Requiere contrato de liquidez por mercado.",
        "source": "liquidity_contract_placeholder",
    }
