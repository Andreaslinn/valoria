"""Demo-only visual fixtures for the Tasar playground redesign."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

CLP_PER_UF_PLAYGROUND = 39_021.9

TASAR_PLAYGROUND_VALUATION: dict[str, Any] = {
    "estimated_price_uf": 6850,
    "estimated_price_clp": 267_300_000,
    "confidence": "high",
    "confidence_score": 0.87,
    "comparable_count": 24,
    "price_m2_uf": 91.3,
    "price_range_low_uf": 6200,
    "price_range_high_uf": 7600,
    "status": "ok",
    "warnings": ["Demo playground: datos simulados para validar UI."],
    "is_demo": True,
    "comparables": [
        {
            "listing_id": 9901,
            "title": "Suecia 150",
            "comuna": "providencia",
            "price_uf": 6900,
            "price_clp": 269_250_000,
            "m2": 75,
            "bedrooms": 3,
            "bathrooms": 2,
            "parking_spaces": 1,
            "similarity": 0.91,
            "date": "10/05/2024",
            "distance": "0,1 km",
        },
        {
            "listing_id": 9902,
            "title": "Los Leones 2100",
            "comuna": "providencia",
            "price_uf": 6750,
            "price_clp": 263_400_000,
            "m2": 72,
            "bedrooms": 2,
            "bathrooms": 2,
            "parking_spaces": 1,
            "similarity": 0.88,
            "date": "28/04/2024",
            "distance": "0,3 km",
        },
        {
            "listing_id": 9903,
            "title": "Holanda 100",
            "comuna": "providencia",
            "price_uf": 6800,
            "price_clp": 265_300_000,
            "m2": 78,
            "bedrooms": 3,
            "bathrooms": 2,
            "parking_spaces": 1,
            "similarity": 0.86,
            "date": "15/04/2024",
            "distance": "0,4 km",
        },
        {
            "listing_id": 9904,
            "title": "Tobalaba 3500",
            "comuna": "providencia",
            "price_uf": 7050,
            "price_clp": 275_200_000,
            "m2": 80,
            "bedrooms": 3,
            "bathrooms": 2,
            "parking_spaces": 2,
            "similarity": 0.84,
            "date": "08/05/2024",
            "distance": "0,6 km",
        },
    ],
}

TASAR_PLAYGROUND_PANEL: dict[str, Any] = {
    "location": {
        "label": "Ubicacion actual",
        "value": "Providencia, RM",
        "address": "Suecia 123, Providencia",
        "radius": "R 400m",
        "environment": "Excelente",
        "connectivity": "Alta",
        "services": "Muy alta",
    },
    "price_trend": {
        "title": "Tendencia de precio (UF/m2)",
        "period": "12 meses",
        "labels": ["May", "Jul", "Sep", "Nov", "Ene", "Mar", "May"],
        "values": [43, 56, 69, 77, 83, 88, 84],
    },
    "confidence": {
        "label": "Nivel de confianza",
        "value": "Alto",
        "score": "87%",
        "detail": "Modelo Premium",
    },
    "market_signals": [
        {"label": "Demanda", "value": "Alta", "delta": "+18% vs 12M", "tone": "positive"},
        {"label": "Tiempo en venta", "value": "32 dias", "delta": "Prom. sector", "tone": "neutral"},
        {"label": "Liquidez", "value": "Alta", "delta": "Ventas activas", "tone": "positive"},
        {"label": "Stock disponible", "value": "Bajo", "delta": "-12% vs 12M", "tone": "negative"},
    ],
    "recent_activity": [
        {"label": "Tasacion en Suecia 123", "time": "Hoy, 11:24"},
        {"label": "Alerta de precio en Providencia", "time": "Ayer, 18:03"},
        {"label": "Nuevo comparable agregado", "time": "15/05/2024"},
    ],
    "risk": {
        "label": "Oportunidad moderada",
        "body": "Depto. en Providencia",
        "detail": "Precio 4,2% bajo mercado",
        "tone": "warning",
    },
    "market_footer": {
        "label": "Panorama de mercado - Providencia",
        "items": [
            {"label": "UF/m2 promedio", "value": "UF 85,4", "delta": "+4,2% vs 12M", "tone": "positive"},
            {"label": "Ventas totales (12M)", "value": "1.254", "delta": "+12% vs 12M", "tone": "positive"},
            {"label": "Tiempo promedio", "value": "32 dias", "delta": "-8 dias vs 12M", "tone": "positive"},
            {"label": "Inventario activo", "value": "385", "delta": "-12% vs 12M", "tone": "negative"},
            {"label": "Liquidez", "value": "Alta", "delta": "Ventas activas", "tone": "positive"},
        ],
    },
}


def get_tasar_playground_valuation() -> dict[str, Any]:
    return deepcopy(TASAR_PLAYGROUND_VALUATION)


def get_tasar_playground_panel() -> dict[str, Any]:
    return deepcopy(TASAR_PLAYGROUND_PANEL)
