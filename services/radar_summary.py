"""Lightweight Radar dashboard summary.

This module deliberately does not run opportunity detection. It only exposes
scope/configuration metadata that is safe for the dashboard to load.
"""
from __future__ import annotations

from typing import Any

from domain.radar.scope import parse_allowed_property_types


def build_radar_summary(*, allowed_property_types: str) -> dict[str, Any]:
    allowed = parse_allowed_property_types(allowed_property_types)
    return {
        "status": "available",
        "mode": "manual",
        "auto_run": False,
        "title": "Oportunidades bajo demanda",
        "summary": "El dashboard no ejecuta Radar automaticamente.",
        "last_run_at": None,
        "opportunities_count": None,
        "fresh_candidates_count": None,
        "allowed_property_types": list(allowed),
        "requires_manual_run": True,
        "cta_path": "/app/radar",
        "source": "radar_summary_manual_contract",
    }
