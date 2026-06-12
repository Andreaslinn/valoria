"""Demo/lab fixtures for the Alerts playground view."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

ALERTS_DEMO_SOURCE = "demo/lab"

ALERTS_DEMO_FIXTURES: dict[str, Any] = {
    "summary": {
        "new_today": 18,
        "new_today_delta": "+28% vs ayer",
        "critical": 3,
        "critical_delta": "+50% vs ayer",
        "saved_rules": 12,
        "saved_rules_caption": "Activas",
        "response_time": "2h 34m",
        "response_time_delta": "-18% vs semana pasada",
    },
    "filters": {
        "severity": ("Todas", "Critica", "Media", "Baja"),
        "commune": ("Todas", "Providencia", "Las Condes", "Nunoa", "Santiago", "La Reina"),
        "property_type": ("Todas", "Departamento", "Casa"),
        "date": ("Ultimos 7 dias", "Hoy", "Ultimos 30 dias"),
    },
    "alert_groups": [
        {
            "title": "Alertas criticas",
            "count": 3,
            "tone": "critical",
            "items": [
                {
                    "icon": "drop",
                    "title": "Caida de precio significativa",
                    "description": "Departamento 2D/2B en Providencia. Precio bajo -9,2% en 24h.",
                    "commune": "Providencia",
                    "address": "Suecia 123",
                    "date": "Hoy, 11:24",
                    "metric": "UF 8.080",
                    "metric_delta": "-9,2%",
                    "tone": "critical",
                },
                {
                    "icon": "target",
                    "title": "Bajo precio vs mercado",
                    "description": "Departamento 1D/1B en Nunoa. Valor estimado UF 5.800.",
                    "commune": "Nunoa",
                    "address": "Irarrrazaval 2500",
                    "date": "Hoy, 10:51",
                    "metric": "-14,7%",
                    "metric_delta": "bajo mercado",
                    "tone": "critical",
                },
                {
                    "icon": "bolt",
                    "title": "Anomalia detectada en publicacion",
                    "description": "Precio por m2 muy por debajo del rango esperado.",
                    "commune": "Santiago",
                    "address": "San Diego 313",
                    "date": "Hoy, 09:18",
                    "metric": "UF 24/m2",
                    "metric_delta": "Anomalo",
                    "tone": "critical",
                },
            ],
        },
        {
            "title": "Alertas medias",
            "count": 6,
            "tone": "medium",
            "items": [
                {
                    "icon": "scale",
                    "title": "Nuevo comparable disponible",
                    "description": "Departamento similar publicado a 0,4 km.",
                    "commune": "Las Condes",
                    "address": "Alonso de Cordova 5870",
                    "date": "Hoy, 10:32",
                    "metric": "UF 7.250",
                    "metric_delta": "0,4 km",
                    "tone": "medium",
                }
            ],
        },
        {
            "title": "Alertas bajas",
            "count": 9,
            "tone": "low",
            "items": [
                {
                    "icon": "wave",
                    "title": "Cambio en liquidez de la zona",
                    "description": "Mayor tiempo en venta durante la ultima semana.",
                    "commune": "La Reina",
                    "address": "Principe de Gales",
                    "date": "Ayer, 18:47",
                    "metric": "38 dias",
                    "metric_delta": "+10 dias",
                    "tone": "low",
                }
            ],
        },
    ],
    "trends": [
        {"label": "Caida de precio", "count": 28, "delta": "+32%", "tone": "negative"},
        {"label": "Bajo precio", "count": 17, "delta": "+19%", "tone": "positive"},
        {"label": "Nuevos comparables", "count": 24, "delta": "+27%", "tone": "positive"},
        {"label": "Cambio de liquidez", "count": 15, "delta": "+7%", "tone": "positive"},
        {"label": "Anomalias detectadas", "count": 6, "delta": "-14%", "tone": "negative"},
        {"label": "Eventos watchlist", "count": 11, "delta": "+10%", "tone": "positive"},
    ],
    "zones": [
        {"name": "Providencia", "count": 24, "level": "Alta", "delta": "+31%"},
        {"name": "Las Condes", "count": 21, "level": "Alta", "delta": "+18%"},
        {"name": "Nunoa", "count": 16, "level": "Media", "delta": "+12%"},
        {"name": "Santiago", "count": 14, "level": "Media", "delta": "-5%"},
        {"name": "La Reina", "count": 9, "level": "Baja", "delta": "+6%"},
    ],
    "settings": [
        {"label": "Canal principal", "value": "Email", "enabled": False, "kind": "route"},
        {"label": "Notificaciones push", "value": "Activadas", "enabled": True, "kind": "switch"},
        {"label": "Alertas criticas", "value": "Instantaneas", "enabled": False, "kind": "route"},
        {"label": "Resumen diario", "value": "08:00 AM", "enabled": True, "kind": "switch"},
        {"label": "Resumen semanal", "value": "Lunes 09:00 AM", "enabled": True, "kind": "switch"},
    ],
}


def get_alerts_demo_fixtures() -> dict[str, Any]:
    """Return an isolated copy of Alerts demo/lab fixtures."""
    return deepcopy(ALERTS_DEMO_FIXTURES)
