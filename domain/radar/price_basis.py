"""Canonical price basis helpers for Radar opportunity detection."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from core.entities.listing import Listing


@dataclass(frozen=True)
class RadarPriceBasis:
    price_currency: str | None
    price_uf: Decimal | None
    price_clp_snapshot: Decimal
    price_basis_used: str
    price_data_quality: str
    exclude_reason: str | None = None

    @property
    def is_usable_for_strong_opportunity(self) -> bool:
        return self.exclude_reason is None


def radar_price_basis(listing: Listing) -> RadarPriceBasis:
    currency = _canonical_currency(listing.price_currency, listing.raw_metadata)
    price_uf = _decimal_or_none(listing.price_uf) or _metadata_decimal(listing.raw_metadata, "price_uf")
    price_clp_snapshot = Decimal(listing.price.clp)
    if currency == "UF":
        if price_uf is None:
            return RadarPriceBasis(
                price_currency="UF",
                price_uf=None,
                price_clp_snapshot=price_clp_snapshot,
                price_basis_used="excluded_legacy_uf_missing_price_uf",
                price_data_quality="legacy_unrecoverable",
                exclude_reason="legacy_uf_missing_price_uf",
            )
        weak_reason = _weak_uf_reason(listing)
        if weak_reason is not None:
            return RadarPriceBasis(
                price_currency="UF",
                price_uf=price_uf,
                price_clp_snapshot=price_clp_snapshot,
                price_basis_used="excluded_weak_uf_price",
                price_data_quality=weak_reason,
                exclude_reason=weak_reason,
            )
        return RadarPriceBasis(
            price_currency="UF",
            price_uf=price_uf,
            price_clp_snapshot=price_clp_snapshot,
            price_basis_used="uf",
            price_data_quality=_uf_quality(listing),
        )
    if currency == "CLP":
        return RadarPriceBasis(
            price_currency="CLP",
            price_uf=None,
            price_clp_snapshot=price_clp_snapshot,
            price_basis_used="clp",
            price_data_quality="canonical_clp",
        )
    return RadarPriceBasis(
        price_currency=currency,
        price_uf=None,
        price_clp_snapshot=price_clp_snapshot,
        price_basis_used="clp_legacy",
        price_data_quality="legacy_unknown_currency",
    )


def canonical_discount_pct(
    *,
    market_price_clp: Decimal,
    listing_basis: RadarPriceBasis,
    uf_to_clp: Decimal,
) -> float | None:
    if market_price_clp <= 0:
        return None
    if not listing_basis.is_usable_for_strong_opportunity:
        return None
    if listing_basis.price_basis_used == "uf":
        if listing_basis.price_uf is None or uf_to_clp <= 0:
            return None
        market_price_uf = market_price_clp / uf_to_clp
        if market_price_uf <= 0:
            return None
        return float((market_price_uf - listing_basis.price_uf) / market_price_uf)
    listed_price = listing_basis.price_clp_snapshot
    return float((market_price_clp - listed_price) / market_price_clp)


def display_price_uf(listing: Listing, uf_to_clp: Decimal) -> float:
    basis = radar_price_basis(listing)
    if basis.price_uf is not None:
        return float(basis.price_uf)
    if uf_to_clp <= 0:
        return 0.0
    return float(Decimal(listing.price.clp) / uf_to_clp)


def _uf_quality(listing: Listing) -> str:
    source = str(listing.price_uf_source or "").strip()
    if source == "legacy_unrecoverable":
        return "legacy_unrecoverable"
    if source in {"scraped", "recovered_exact", "recovered_high_confidence"}:
        return source
    if source == "estimated":
        return "estimated"
    return "canonical_uf"


def _weak_uf_reason(listing: Listing) -> str | None:
    source = str(listing.price_uf_source or "").strip().lower()
    confidence = str(listing.price_uf_confidence or "").strip().lower()
    if source == "estimated":
        return "estimated_uf_not_strong"
    if confidence == "low":
        return "low_confidence_uf_not_strong"
    return None


def _canonical_currency(value: str | None, raw_metadata: dict | None) -> str | None:
    raw = value or (raw_metadata or {}).get("currency_original") or (raw_metadata or {}).get("price_currency")
    if raw is None and _metadata_decimal(raw_metadata, "price_uf") is not None:
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
