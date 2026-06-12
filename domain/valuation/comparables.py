"""Motor de tasacion por comparables."""
from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import pstdev

from config.constants import (
    COMPARABLES_M2_TOLERANCE,
    COMPARABLES_MAX_DISTANCE_KM,
    MIN_COMPARABLES,
    TOP_N_COMPARABLES,
)
from config.valuation_flags import (
    canonical_price_enabled_for_segment,
    canonical_price_segment_key,
    valuation_canonical_price_enabled as _canonical_price_flag_enabled,
    valuation_canonical_price_segmented_enabled as _canonical_price_segmented_flag_enabled,
)
from core.entities.listing import Listing, Property
from core.entities.opportunity import ValuationResult
from core.exceptions import InsufficientDataError, ValidationError
from core.normalization.property_type import normalize_property_type as _property_type
from core.value_objects.price import Price
from core.value_objects.score import Score
from domain.geocoding.quality import normalized_precision_for
from domain.valuation.beta_scope import assess_beta_scope
from domain.valuation.canonical_price import valuation_price_basis
from domain.valuation.comparable_quality import assess_comparable_quality
from domain.valuation.reliability import assess_comparable_reliability
from domain.valuation.scoring import similarity_score

_PRECISE_GEOCODE_PRECISIONS = {"address"}
_UNKNOWN_PROPERTY_TYPE_CONFIDENCE_FACTOR = 0.65

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValuationRun:
    result: ValuationResult
    scored_comparables: list[tuple[Score, Listing]]


@dataclass(frozen=True)
class _CanonicalPriceSelection:
    scored: list[tuple[Score, Listing]]
    metrics: dict


def valuate(
    target: Property,
    candidates: Sequence[Listing],
    uf_to_clp: Decimal,
    *,
    canonical_price_enabled: bool | None = None,
) -> ValuationResult:
    return valuate_with_comparables(
        target,
        candidates,
        uf_to_clp,
        canonical_price_enabled=canonical_price_enabled,
    ).result


def valuate_with_comparables(
    target: Property,
    candidates: Sequence[Listing],
    uf_to_clp: Decimal,
    *,
    canonical_price_enabled: bool | None = None,
) -> ValuationRun:
    _validate_target(target)
    segment_key = canonical_price_segment_key(target.comuna, _property_type(target))
    use_canonical_price = _resolve_canonical_price_enabled(canonical_price_enabled, target=target)

    eligible = filter_candidates(target, candidates)
    if len(eligible) < MIN_COMPARABLES:
        raise InsufficientDataError(
            f"Solo {len(eligible)} comparables elegibles; "
            f"se requieren al menos {MIN_COMPARABLES}."
        )

    scored_all = score_and_rank(target, eligible)
    price_selection = _select_scored_comparables(
        scored_all,
        uf_to_clp=uf_to_clp,
        canonical_price_enabled=use_canonical_price,
    )
    scored = price_selection.scored

    estimate_area = _built_area(target)
    estimated_ppm2_clp = _weighted_mean_ppm2(
        scored,
        uf_to_clp=uf_to_clp,
        canonical_price_enabled=use_canonical_price,
    )
    estimated_total = estimated_ppm2_clp * Decimal(str(estimate_area))

    range_delta = _range_delta(
        scored,
        target_m2=estimate_area,
        uf_to_clp=uf_to_clp,
        canonical_price_enabled=use_canonical_price,
    )
    low = max(Decimal("0"), estimated_total - range_delta)
    high = estimated_total + range_delta

    base_confidence = _confidence(scored, target)
    reliability = assess_comparable_reliability(
        target=target,
        scored_comparables=scored,
        base_confidence=base_confidence,
    )
    reliability_metrics = dict(reliability.metrics)
    reliability_metrics.update(price_selection.metrics)
    reliability_metrics["canonical_price_segment"] = segment_key
    comparable_quality = assess_comparable_quality(
        target=target,
        scored_comparables=scored,
    )
    beta_scope = assess_beta_scope(
        target=target,
        candidate_pool=candidates,
        comparable_quality=comparable_quality,
    )

    result = ValuationResult(
        estimated_price=Price(clp=estimated_total),
        price_range_low=Price(clp=low),
        price_range_high=Price(clp=high),
        confidence=reliability.confidence,
        comparables_used=len(scored),
        uf_to_clp_rate=uf_to_clp,
        reliability_warnings=list(reliability.warnings),
        reliability_metrics=reliability_metrics,
        base_confidence=base_confidence,
        comparable_quality_level=comparable_quality.level,
        comparable_quality_flags=list(comparable_quality.risk_flags),
        comparable_quality_metrics=comparable_quality.metrics,
        beta_scope_status=beta_scope.status,
        beta_scope_flags=list(beta_scope.flags),
        beta_scope_metrics=beta_scope.metrics,
        beta_scope_message=beta_scope.message,
    )
    return ValuationRun(result=result, scored_comparables=scored)


def filter_candidates(target: Property, candidates: Sequence[Listing]) -> list[Listing]:
    target_built = _built_area(target)
    _validate_built_area(target_built)
    m2_min = target_built * (1.0 - COMPARABLES_M2_TOLERANCE)
    m2_max = target_built * (1.0 + COMPARABLES_M2_TOLERANCE)

    eligible: list[Listing] = []
    for candidate in candidates:
        discard_reason = candidate_discard_reason(target, candidate, m2_min=m2_min, m2_max=m2_max)
        if discard_reason is not None:
            _log.debug(
                "comparable_discard reason=%s target_type=%s candidate_type=%s "
                "target_comuna=%s candidate_comuna=%s candidate_id=%s fingerprint=%s",
                discard_reason,
                _property_type(target),
                _property_type(candidate),
                target.comuna,
                candidate.comuna,
                candidate.id,
                candidate.fingerprint,
            )
            continue
        eligible.append(candidate)
    return eligible


def candidate_discard_reason(
    target: Property,
    candidate: Listing,
    *,
    m2_min: float | None = None,
    m2_max: float | None = None,
) -> str | None:
    target_built = _built_area(target)
    _validate_built_area(target_built)
    if m2_min is None:
        m2_min = target_built * (1.0 - COMPARABLES_M2_TOLERANCE)
    if m2_max is None:
        m2_max = target_built * (1.0 + COMPARABLES_M2_TOLERANCE)

    if candidate.comuna != target.comuna:
        return "comuna_mismatch"
    if _property_type(target) != _property_type(candidate):
        return "property_type_mismatch"
    if not candidate.is_active:
        return "inactive"
    candidate_built = _built_area(candidate)
    if candidate_built is None or candidate_built <= 0:
        return "missing_built_area"
    if not (m2_min <= candidate_built <= m2_max):
        return "area_out_of_range"
    if _property_type(target) == "house" and target.land_area_m2 and candidate.land_area_m2:
        land_min = target.land_area_m2 * (1.0 - COMPARABLES_M2_TOLERANCE)
        land_max = target.land_area_m2 * (1.0 + COMPARABLES_M2_TOLERANCE)
        if not land_min <= candidate.land_area_m2 <= land_max:
            return "area_out_of_range"
    if candidate.price.clp <= 0:
        return "missing_price"
    if _too_far(target, candidate):
        return "too_far"
    return None


def score_and_rank(target: Property, candidates: Sequence[Listing]) -> list[tuple[Score, Listing]]:
    scored = [(similarity_score(target, candidate), candidate) for candidate in candidates]
    scored.sort(key=lambda pair: pair[0].value, reverse=True)
    return scored


def _validate_target(target: Property) -> None:
    _validate_built_area(_built_area(target))
    if not target.comuna:
        raise ValidationError("target.comuna no puede ser vacio")


def _validate_built_area(value: float | None) -> None:
    if value is None or value <= 0:
        raise ValidationError(f"target.built_area_m2 debe ser positivo, recibido {value}")


def _too_far(target: Property, candidate: Listing) -> bool:
    if target.coordinates is None or candidate.coordinates is None:
        return False
    if normalized_precision_for(target) not in _PRECISE_GEOCODE_PRECISIONS:
        return False
    if normalized_precision_for(candidate) not in _PRECISE_GEOCODE_PRECISIONS:
        return False
    return target.coordinates.distance_km(candidate.coordinates) > COMPARABLES_MAX_DISTANCE_KM


def _select_scored_comparables(
    scored_all: Sequence[tuple[Score, Listing]],
    *,
    uf_to_clp: Decimal,
    canonical_price_enabled: bool,
) -> _CanonicalPriceSelection:
    if not canonical_price_enabled:
        return _CanonicalPriceSelection(
            scored=list(scored_all[:TOP_N_COMPARABLES]),
            metrics=_legacy_price_metrics(),
        )

    considered = list(scored_all[:TOP_N_COMPARABLES])
    usable: list[tuple[Score, Listing]] = []
    selected_currency_counts: Counter[str] = Counter()
    for score, listing in scored_all:
        basis = valuation_price_basis(listing, uf_to_clp)
        if basis.is_usable_for_valuation and basis.amount_uf is not None:
            usable.append((score, listing))
            selected_currency_counts[basis.price_unit or "unknown"] += 1
            if len(usable) >= TOP_N_COMPARABLES:
                break
            continue

    if len(usable) < MIN_COMPARABLES:
        raise InsufficientDataError(
            f"Solo {len(usable)} comparables con precio canonico usable; "
            f"se requieren al menos {MIN_COMPARABLES}."
        )
    metrics = _canonical_price_metrics(
        considered=considered,
        selected=usable,
        selected_currency_counts=selected_currency_counts,
        uf_to_clp=uf_to_clp,
    )
    return _CanonicalPriceSelection(scored=usable, metrics=metrics)


def _weighted_mean_ppm2(
    scored: Sequence[tuple[Score, Listing]],
    *,
    uf_to_clp: Decimal | None = None,
    canonical_price_enabled: bool = False,
) -> Decimal:
    total_weight = Decimal("0")
    weighted_sum = Decimal("0")
    for score, listing in scored:
        area = _built_area(listing)
        if area is None or area <= 0:
            continue
        weight = Decimal(str(score.value))
        price_per_m2 = _price_per_m2_for_valuation(
            listing,
            area=area,
            uf_to_clp=uf_to_clp,
            canonical_price_enabled=canonical_price_enabled,
        )
        if price_per_m2 is None:
            continue
        weighted_sum += weight * price_per_m2
        total_weight += weight

    if total_weight == 0:
        raise InsufficientDataError("Pesos de comparables suman 0")
    return weighted_sum / total_weight


def _range_delta(
    scored: Sequence[tuple[Score, Listing]],
    *,
    target_m2: float,
    uf_to_clp: Decimal | None = None,
    canonical_price_enabled: bool = False,
) -> Decimal:
    ppm2_values = [
        float(price_per_m2)
        for _, listing in scored
        if (area := _built_area(listing)) is not None and area > 0
        if (
            price_per_m2 := _price_per_m2_for_valuation(
                listing,
                area=area,
                uf_to_clp=uf_to_clp,
                canonical_price_enabled=canonical_price_enabled,
            )
        ) is not None
    ]
    if len(ppm2_values) < 2:
        return Decimal("0")
    return Decimal(str(pstdev(ppm2_values))) * Decimal(str(target_m2))


def _confidence(scored: Sequence[tuple[Score, Listing]], target: Property) -> Score:
    n = len(scored)
    avg_score = sum(score.value for score, _ in scored) / n
    n_factor = min(1.0, n / 15.0)
    confidence = 0.7 * avg_score + 0.3 * n_factor
    if _property_type(target) == "unknown":
        confidence *= _UNKNOWN_PROPERTY_TYPE_CONFIDENCE_FACTOR
    if any(_property_type(listing) == "house" for _, listing in scored):
        with_land = sum(1 for _, listing in scored if listing.land_area_m2 is not None)
        confidence *= 0.75 + 0.25 * (with_land / n)
    return Score.clamped(confidence)


def _built_area(value: Property | Listing) -> float | None:
    return getattr(value, "built_area_m2", None) or getattr(value, "usable_area_m2", None) or value.m2


def _price_per_m2_for_valuation(
    listing: Listing,
    *,
    area: float,
    uf_to_clp: Decimal | None,
    canonical_price_enabled: bool,
) -> Decimal | None:
    if not canonical_price_enabled:
        return listing.price.clp / Decimal(str(area))
    if uf_to_clp is None or uf_to_clp <= 0:
        return None
    basis = valuation_price_basis(listing, uf_to_clp)
    if not basis.is_usable_for_valuation or basis.amount_uf is None:
        return None
    return (basis.amount_uf / Decimal(str(area))) * uf_to_clp


def _resolve_canonical_price_enabled(value: bool | None, *, target: Property) -> bool:
    if value is not None:
        return bool(value)
    if _canonical_price_flag_enabled():
        return True
    if _canonical_price_segmented_flag_enabled():
        return canonical_price_enabled_for_segment(target.comuna, _property_type(target))
    return False


def _legacy_price_metrics() -> dict:
    return {
        "canonical_price_enabled": False,
        "canonical_price_mode": "legacy",
        "canonical_price_coverage": None,
        "mixed_currency_share": None,
        "excluded_price_quality_count": {},
    }


def _canonical_price_metrics(
    *,
    considered: Sequence[tuple[Score, Listing]],
    selected: Sequence[tuple[Score, Listing]],
    selected_currency_counts: Counter[str],
    uf_to_clp: Decimal,
) -> dict:
    considered_count = len(considered)
    considered_usable = 0
    considered_excluded: Counter[str] = Counter()
    for _, listing in considered:
        basis = valuation_price_basis(listing, uf_to_clp)
        if basis.is_usable_for_valuation:
            considered_usable += 1
        else:
            considered_excluded[_price_quality_bucket(basis.exclusion_reason or basis.quality)] += 1
    return {
        "canonical_price_enabled": True,
        "canonical_price_mode": "canonical",
        "canonical_price_coverage": (
            considered_usable / considered_count if considered_count else None
        ),
        "canonical_price_coverage_pct": (
            round(considered_usable / considered_count * 100, 2) if considered_count else None
        ),
        "mixed_currency_share": _mixed_currency_share(selected_currency_counts),
        "mixed_currency_share_pct": _mixed_currency_share_pct(selected_currency_counts),
        "excluded_price_quality_count": dict(sorted(considered_excluded.items())),
        "selected_canonical_comparables": len(selected),
    }


def _mixed_currency_share(currency_counts: Counter[str]) -> float | None:
    total = sum(currency_counts.values())
    if total == 0:
        return None
    if len([count for count in currency_counts.values() if count > 0]) <= 1:
        return 0.0
    dominant = max(currency_counts.values())
    return (total - dominant) / total


def _mixed_currency_share_pct(currency_counts: Counter[str]) -> float | None:
    share = _mixed_currency_share(currency_counts)
    if share is None:
        return None
    return round(share * 100, 2)


def _price_quality_bucket(reason: str | None) -> str:
    if reason in {"legacy_uf_missing_price_uf", "legacy_unrecoverable"}:
        return "legacy"
    if reason in {"estimated_uf_not_strong", "low_confidence_uf_not_strong"}:
        return "estimated_or_low"
    if reason == "uf_fallback_not_canonical":
        return "fallback"
    if reason in {"unknown_currency", "legacy_unknown_currency"}:
        return "unknown_currency"
    if reason in {"missing_clp_price", "invalid_uf_rate"}:
        return "invalid_clp"
    return str(reason or "unknown")
