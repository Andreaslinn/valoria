"""Canonical price basis helpers for valuation experiments.

This module is intentionally read-only and side-effect free. It does not change
the production valuation engine; it only exposes the price basis a future
UF-aware valuation can use.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from core.entities.listing import Listing


STRONG_UF_SOURCES = frozenset({"scraped", "recovered_exact", "recovered_high_confidence"})
WEAK_UF_SOURCES = frozenset({"estimated"})
LEGACY_UF_SOURCES = frozenset({"legacy_unrecoverable"})
FALLBACK_SOURCES = frozenset({"fallback", "uf_fallback", "derived_fallback"})


@dataclass(frozen=True)
class ValuationPriceBasis:
    amount_uf: Decimal | None
    amount_clp_display: Decimal | None
    price_unit: str | None
    basis_used: str
    quality: str
    is_usable_for_valuation: bool
    weight_factor: Decimal
    exclusion_reason: str | None = None


def valuation_price_basis(listing: Listing, uf_to_clp: Decimal) -> ValuationPriceBasis:
    """Return canonical valuation price basis for a listing.

    Rules for phase 1:
    - Strong UF prices are usable as native UF.
    - Estimated/low-confidence UF prices are excluded from strict valuation.
    - Legacy UF rows without canonical UF are excluded.
    - CLP rows are usable after conversion to UF for the valuation run.
    - Unknown currency is excluded.
    """
    currency = _canonical_currency(listing.price_currency, listing.raw_metadata)
    price_uf = _decimal_or_none(listing.price_uf) or _metadata_decimal(listing.raw_metadata, "price_uf")
    price_clp = _decimal_or_none(listing.price.clp)

    if currency == "UF":
        if _has_fallback_provenance(listing):
            return _excluded(
                price_unit="UF",
                basis_used="excluded_uf_fallback",
                quality="fallback_not_canonical",
                amount_clp_display=price_clp,
                reason="uf_fallback_not_canonical",
            )
        if price_uf is None:
            return _excluded(
                price_unit="UF",
                basis_used="excluded_legacy_uf_missing_price_uf",
                quality="legacy_unrecoverable",
                amount_clp_display=price_clp,
                reason="legacy_uf_missing_price_uf",
            )
        weak_reason = _weak_uf_reason(listing)
        if weak_reason is not None:
            return _excluded(
                price_unit="UF",
                basis_used="excluded_weak_uf_price",
                quality=weak_reason,
                amount_uf=price_uf,
                amount_clp_display=_display_clp(price_uf, price_clp, uf_to_clp),
                reason=weak_reason,
            )
        return ValuationPriceBasis(
            amount_uf=price_uf,
            amount_clp_display=_display_clp(price_uf, price_clp, uf_to_clp),
            price_unit="UF",
            basis_used="canonical_uf",
            quality=_uf_quality(listing),
            is_usable_for_valuation=True,
            weight_factor=Decimal("1"),
            exclusion_reason=None,
        )

    if currency == "CLP":
        if price_clp is None or price_clp <= 0:
            return _excluded(
                price_unit="CLP",
                basis_used="excluded_clp_missing_price",
                quality="missing_clp",
                reason="missing_clp_price",
            )
        if uf_to_clp <= 0:
            return _excluded(
                price_unit="CLP",
                basis_used="excluded_invalid_uf_rate",
                quality="invalid_uf_rate",
                amount_clp_display=price_clp,
                reason="invalid_uf_rate",
            )
        return ValuationPriceBasis(
            amount_uf=(price_clp / uf_to_clp).quantize(Decimal("0.01")),
            amount_clp_display=price_clp,
            price_unit="CLP",
            basis_used="canonical_clp_converted",
            quality="canonical_clp",
            is_usable_for_valuation=True,
            weight_factor=Decimal("1"),
            exclusion_reason=None,
        )

    return _excluded(
        price_unit=currency,
        basis_used="excluded_unknown_currency",
        quality="legacy_unknown_currency",
        amount_clp_display=price_clp,
        reason="unknown_currency",
    )


def _excluded(
    *,
    price_unit: str | None,
    basis_used: str,
    quality: str,
    reason: str,
    amount_uf: Decimal | None = None,
    amount_clp_display: Decimal | None = None,
) -> ValuationPriceBasis:
    return ValuationPriceBasis(
        amount_uf=amount_uf,
        amount_clp_display=amount_clp_display,
        price_unit=price_unit,
        basis_used=basis_used,
        quality=quality,
        is_usable_for_valuation=False,
        weight_factor=Decimal("0"),
        exclusion_reason=reason,
    )


def _display_clp(price_uf: Decimal, price_clp_snapshot: Decimal | None, uf_to_clp: Decimal) -> Decimal | None:
    if uf_to_clp > 0:
        return (price_uf * uf_to_clp).quantize(Decimal("1"))
    return price_clp_snapshot


def _uf_quality(listing: Listing) -> str:
    source = str(listing.price_uf_source or "").strip().lower()
    confidence = str(listing.price_uf_confidence or "").strip().lower()
    if source in STRONG_UF_SOURCES:
        return source
    if confidence == "high":
        return "canonical_uf_high_confidence"
    return "canonical_uf"


def _weak_uf_reason(listing: Listing) -> str | None:
    source = str(listing.price_uf_source or "").strip().lower()
    confidence = str(listing.price_uf_confidence or "").strip().lower()
    if source in WEAK_UF_SOURCES:
        return "estimated_uf_not_strong"
    if confidence == "low":
        return "low_confidence_uf_not_strong"
    return None


def _has_fallback_provenance(listing: Listing) -> bool:
    values = {
        str(listing.price_uf_source or "").strip().lower(),
        str(listing.price_recovery_method or "").strip().lower(),
        str(listing.price_uf_confidence or "").strip().lower(),
    }
    metadata = listing.raw_metadata if isinstance(listing.raw_metadata, dict) else {}
    values.add(str(metadata.get("price_uf_source") or "").strip().lower())
    values.add(str(metadata.get("price_recovery_method") or "").strip().lower())
    values.add(str(metadata.get("price_conversion_source") or "").strip().lower())
    return bool(values & FALLBACK_SOURCES)


def _canonical_currency(value: str | None, raw_metadata: dict | None) -> str | None:
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    raw = value or metadata.get("currency_original") or metadata.get("price_currency") or metadata.get("currency")
    if raw is None and _metadata_decimal(metadata, "price_uf") is not None:
        return "UF"
    if raw is None:
        return None
    text = str(raw).strip().upper()
    if text in {"UF", "CLF"}:
        return "UF"
    if text in {"CLP", "$", "PESO", "PESOS"}:
        return "CLP"
    return text[:16] or None


def _metadata_decimal(raw_metadata: dict | None, key: str) -> Decimal | None:
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    return _decimal_or_none(metadata.get(key))


def _decimal_or_none(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed.quantize(Decimal("0.01"))
