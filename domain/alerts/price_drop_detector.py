"""Pure price-drop detection from price history."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


@dataclass(frozen=True)
class PricePoint:
    price_clp: int | float | Decimal | None
    observed_at: datetime | str | None
    price_uf: int | float | Decimal | None = None
    price_clp_snapshot: int | float | Decimal | None = None
    price_currency: str | None = None
    change_basis: str | None = None
    is_artifact: bool = False
    price_uf_source: str | None = None
    price_uf_confidence: str | None = None
    price_recovery_method: str | None = None


def detect_price_drop_from_history(
    price_history: list[dict[str, Any]] | list[PricePoint],
    threshold_pct: float = 5.0,
) -> dict[str, Any] | None:
    points = _valid_points(price_history)
    if len(points) < 2:
        return None

    points.sort(key=lambda item: item["observed_at"], reverse=True)
    latest = points[0]
    previous = points[1]
    currency = _canonical_currency(latest.get("price_currency") or previous.get("price_currency"))
    if currency == "UF":
        previous_price = previous.get("price_uf")
        new_price = latest.get("price_uf")
        if previous_price is None or new_price is None:
            return None
        basis = "uf"
    else:
        previous_price = previous["price_clp_snapshot"] or previous["price_clp"]
        new_price = latest["price_clp_snapshot"] or latest["price_clp"]
        basis = "clp" if currency == "CLP" else "clp_legacy"
    if previous_price <= 0 or new_price >= previous_price:
        return None

    drop_pct = _round_pct(((previous_price - new_price) / previous_price) * Decimal("100"))
    if drop_pct < Decimal(str(threshold_pct)):
        return None

    return {
        "previous_price_clp": _int_or_none(previous["price_clp_snapshot"] or previous["price_clp"]),
        "new_price_clp": _int_or_none(latest["price_clp_snapshot"] or latest["price_clp"]),
        "previous_price_uf": _float_or_none(previous.get("price_uf")),
        "new_price_uf": _float_or_none(latest.get("price_uf")),
        "previous_price_clp_snapshot": _int_or_none(previous["price_clp_snapshot"] or previous["price_clp"]),
        "new_price_clp_snapshot": _int_or_none(latest["price_clp_snapshot"] or latest["price_clp"]),
        "price_currency": currency or "CLP",
        "change_basis": previous.get("change_basis") or basis,
        "canonical_previous_price": _float_or_none(previous.get("price_uf")) if currency == "UF" else _int_or_none(previous["price_clp_snapshot"] or previous["price_clp"]),
        "canonical_new_price": _float_or_none(latest.get("price_uf")) if currency == "UF" else _int_or_none(latest["price_clp_snapshot"] or latest["price_clp"]),
        "canonical_price_unit": "UF" if currency == "UF" else "CLP",
        "display_previous_price_clp": _int_or_none(previous["price_clp_snapshot"] or previous["price_clp"]),
        "display_new_price_clp": _int_or_none(latest["price_clp_snapshot"] or latest["price_clp"]),
        "artifact_filtered": False,
        "drop_pct": float(drop_pct),
        "detected_at": latest["observed_at"],
    }


def _valid_points(price_history: list[dict[str, Any]] | list[PricePoint]) -> list[dict[str, Any]]:
    valid: list[dict[str, Any]] = []
    for raw in price_history:
        if _is_artifact(raw):
            continue
        if _is_legacy_unrecoverable_uf(raw):
            continue
        if _is_weak_estimated_uf(raw):
            continue
        price = _price(raw)
        observed_at = _observed_at(raw)
        if price is None or observed_at is None:
            continue
        valid.append(
            {
                "price_clp": price,
                "price_clp_snapshot": _decimal_field(raw, "price_clp_snapshot"),
                "price_uf": _decimal_field(raw, "price_uf"),
                "price_currency": _field(raw, "price_currency"),
                "change_basis": _field(raw, "change_basis"),
                "observed_at": observed_at,
            }
        )
    return valid


def _price(raw: dict[str, Any] | PricePoint) -> Decimal | None:
    value = _field(raw, "price_clp")
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _observed_at(raw: dict[str, Any] | PricePoint) -> datetime | None:
    value = raw.observed_at if isinstance(raw, PricePoint) else raw.get("observed_at")
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _field(raw: dict[str, Any] | PricePoint, name: str) -> Any:
    return getattr(raw, name) if isinstance(raw, PricePoint) else raw.get(name)


def _decimal_field(raw: dict[str, Any] | PricePoint, name: str) -> Decimal | None:
    value = _field(raw, name)
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _is_artifact(raw: dict[str, Any] | PricePoint) -> bool:
    return bool(_field(raw, "is_artifact"))


def _is_legacy_unrecoverable_uf(raw: dict[str, Any] | PricePoint) -> bool:
    currency = _canonical_currency(_field(raw, "price_currency"))
    if currency != "UF":
        return False
    if _decimal_field(raw, "price_uf") is not None:
        return False
    return _field(raw, "price_uf_source") == "legacy_unrecoverable" or _field(raw, "price_recovery_method") == "legacy_unrecoverable"


def _is_weak_estimated_uf(raw: dict[str, Any] | PricePoint) -> bool:
    if _canonical_currency(_field(raw, "price_currency")) != "UF":
        return False
    source = str(_field(raw, "price_uf_source") or "").strip().lower()
    confidence = str(_field(raw, "price_uf_confidence") or "").strip().lower()
    return source == "estimated" or confidence == "low"


def _canonical_currency(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if text in {"UF", "CLF"}:
        return "UF"
    if text in {"CLP", "$", "PESO", "PESOS"}:
        return "CLP"
    return text or None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(Decimal(str(value)))
    except Exception:
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(Decimal(str(value)))
    except Exception:
        return None


def _round_pct(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
