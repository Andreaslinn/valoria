"""Formatting helpers for the Streamlit UI."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from core.assessment.confidence import normalize_confidence_label

EMPTY = "—"


def none_dash(value: Any) -> str:
    return EMPTY if value is None or value == "" else str(value)


def format_clp(value: Any) -> str:
    number = _to_decimal(value)
    if number is None:
        return EMPTY
    return f"${int(number):,}".replace(",", ".")


def format_uf(value: Any) -> str:
    number = _to_decimal(value)
    if number is None:
        return EMPTY
    return f"UF {number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_pct(value: Any) -> str:
    number = _to_decimal(value)
    if number is None:
        return EMPTY
    return f"{number:.2f}%".replace(".", ",")


def format_m2(value: Any) -> str:
    number = _to_decimal(value)
    if number is None:
        return EMPTY
    return f"{number:.1f} m²".replace(".", ",")


def format_confidence(value: Any) -> str:
    labels = {
        "high": "Alta",
        "medium": "Media",
        "low": "Baja",
        "insufficient_data": "Datos insuficientes",
        "unknown": "No disponible",
        "ok": "OK",
        "error": "Error",
    }
    if value is None:
        return EMPTY
    normalized = normalize_confidence_label(value)
    return labels.get(normalized, str(value).title())


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
