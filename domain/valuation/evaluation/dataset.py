"""Dataset construction for offline valuation engine evaluation."""
from __future__ import annotations

import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from core.entities.listing import Listing, Property
from core.normalization.property_type import normalize_property_type


@dataclass(frozen=True)
class EvaluationCase:
    target_id: int | None
    target: Property
    actual_price_clp: Decimal
    actual_price_uf: Decimal | None
    listing: Listing
    candidates: tuple[Listing, ...]
    metadata: dict = field(default_factory=dict)


def build_evaluation_cases(
    listings: Sequence[Listing],
    *,
    limit: int | None = None,
    property_type: str | None = None,
    seed: int = 42,
    cutoff: datetime | None = None,
) -> list[EvaluationCase]:
    """Build holdout-like cases from active listings.

    The target listing itself and evident duplicates are excluded from the
    candidate pool. When a cutoff is supplied, listings after it are excluded.
    This is still an active-listing benchmark, not a full temporal backtest.
    """

    normalized_type = normalize_property_type(property_type) if property_type else None
    stable_listings = sorted(listings, key=_listing_sort_key)
    eligible = [
        listing
        for listing in stable_listings
        if _is_eligible_target(listing, property_type=normalized_type, cutoff=cutoff)
    ]
    rng = random.Random(seed)
    rng.shuffle(eligible)
    if limit is not None:
        eligible = eligible[: max(0, limit)]

    cases: list[EvaluationCase] = []
    for listing in eligible:
        target = _property_from_listing(listing)
        candidates = tuple(
            candidate
            for candidate in stable_listings
            if _is_eligible_candidate(candidate, target=listing, cutoff=cutoff)
        )
        cases.append(
            EvaluationCase(
                target_id=listing.id,
                target=target,
                actual_price_clp=listing.price.clp,
                actual_price_uf=listing.price_uf,
                listing=listing,
                candidates=candidates,
                metadata={
                    "source": listing.source,
                    "fingerprint": listing.fingerprint,
                    "scraped_at": listing.scraped_at.isoformat() if listing.scraped_at else None,
                    "candidate_count": len(candidates),
                },
            )
        )
    return cases


def infer_uf_rate(listings: Iterable[Listing]) -> Decimal | None:
    """Infer a data-derived UF/CLP rate from canonical UF fields."""

    ratios: list[Decimal] = []
    for listing in listings:
        if listing.price_uf is None or listing.price_uf <= 0 or listing.price.clp <= 0:
            continue
        try:
            ratios.append(listing.price.clp / Decimal(str(listing.price_uf)))
        except (InvalidOperation, ZeroDivisionError):
            continue
    if not ratios:
        return None
    ratios.sort()
    mid = len(ratios) // 2
    if len(ratios) % 2:
        return ratios[mid]
    return (ratios[mid - 1] + ratios[mid]) / Decimal("2")


def _property_from_listing(listing: Listing) -> Property:
    built_area = listing.built_area_m2 or listing.usable_area_m2 or listing.m2
    raw_metadata = dict(listing.raw_metadata or {})
    if listing.title:
        raw_metadata.setdefault("title", listing.title)
    return Property(
        id=listing.property_id or listing.id,
        comuna=listing.comuna,
        m2=built_area or listing.m2 or 0,
        bedrooms=listing.bedrooms,
        bathrooms=listing.bathrooms,
        parking=listing.parking,
        property_type=normalize_property_type(listing),
        built_area_m2=built_area,
        land_area_m2=listing.land_area_m2,
        usable_area_m2=listing.usable_area_m2,
        coordinates=listing.coordinates,
        geocode_precision=listing.geocode_precision,
        raw_metadata=raw_metadata,
    )


def _is_eligible_target(
    listing: Listing,
    *,
    property_type: str | None,
    cutoff: datetime | None,
) -> bool:
    if not listing.is_active:
        return False
    if listing.price.clp <= 0:
        return False
    if _built_area(listing) is None:
        return False
    if property_type is not None and normalize_property_type(listing) != property_type:
        return False
    if cutoff is not None and listing.scraped_at and listing.scraped_at > cutoff:
        return False
    return True


def _is_eligible_candidate(
    candidate: Listing,
    *,
    target: Listing,
    cutoff: datetime | None,
) -> bool:
    if not candidate.is_active or candidate.price.clp <= 0:
        return False
    if cutoff is not None and candidate.scraped_at and candidate.scraped_at > cutoff:
        return False
    if target.id is not None and candidate.id == target.id:
        return False
    if candidate.fingerprint and candidate.fingerprint == target.fingerprint:
        return False
    if candidate.source == target.source and candidate.external_id and candidate.external_id == target.external_id:
        return False
    if candidate.url and target.url and candidate.url == target.url:
        return False
    return True


def _built_area(listing: Listing) -> float | None:
    value = listing.built_area_m2 or listing.usable_area_m2 or listing.m2
    return value if value and value > 0 else None


def _listing_sort_key(listing: Listing) -> tuple[str, str, str, str]:
    return (
        str(listing.id if listing.id is not None else ""),
        str(listing.source or ""),
        str(listing.external_id or ""),
        str(listing.fingerprint or ""),
    )
