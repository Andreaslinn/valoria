"""Read-only comparable quality helpers for AVM calibration audits.

The functions here are pure diagnostics. They do not change productive
comparable selection, scoring, or valuation behavior.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from statistics import mean, median
from typing import Any


@dataclass(frozen=True)
class QualityThresholds:
    subject_low_ratio: float = 0.70
    subject_high_ratio: float = 1.45
    reference_low_ratio: float = 0.65
    reference_high_ratio: float = 1.55
    strict_reference_low_ratio: float = 0.55
    strict_reference_high_ratio: float = 1.85
    surface_far_ratio: float = 0.25
    stale_days: int = 120
    min_comparables_after_filter: int = 5
    trim_ratio: float = 0.10
    winsor_ratio: float = 0.10

    def as_dict(self) -> dict[str, float | int]:
        return {
            "subject_low_ratio": self.subject_low_ratio,
            "subject_high_ratio": self.subject_high_ratio,
            "reference_low_ratio": self.reference_low_ratio,
            "reference_high_ratio": self.reference_high_ratio,
            "strict_reference_low_ratio": self.strict_reference_low_ratio,
            "strict_reference_high_ratio": self.strict_reference_high_ratio,
            "surface_far_ratio": self.surface_far_ratio,
            "stale_days": self.stale_days,
            "min_comparables_after_filter": self.min_comparables_after_filter,
            "trim_ratio": self.trim_ratio,
            "winsor_ratio": self.winsor_ratio,
        }


@dataclass(frozen=True)
class PriceM2Reference:
    sample_count: int
    median: float | None
    p10: float | None
    p25: float | None
    p75: float | None
    p90: float | None
    iqr: float | None

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "sample_count": self.sample_count,
            "median": _round(self.median),
            "p10": _round(self.p10),
            "p25": _round(self.p25),
            "p75": _round(self.p75),
            "p90": _round(self.p90),
            "iqr": _round(self.iqr),
        }


@dataclass(frozen=True)
class ComparableQualityFlags:
    flags: tuple[str, ...]
    price_m2_uf: float | None
    subject_ratio: float | None
    comuna_ratio: float | None
    pool_ratio: float | None
    surface_diff_pct: float | None
    economic_outlier: bool
    strict_economic_outlier: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "flags": list(self.flags),
            "price_m2_uf": _round(self.price_m2_uf),
            "subject_ratio": _round(self.subject_ratio, 4),
            "comuna_ratio": _round(self.comuna_ratio, 4),
            "pool_ratio": _round(self.pool_ratio, 4),
            "surface_diff_pct": _round(self.surface_diff_pct, 2),
            "economic_outlier": self.economic_outlier,
            "strict_economic_outlier": self.strict_economic_outlier,
        }


@dataclass(frozen=True)
class EstimatorResult:
    name: str
    price_m2_uf: float | None
    comparable_count: int
    filtered_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "price_m2_uf": _round(self.price_m2_uf),
            "comparable_count": self.comparable_count,
            "filtered_count": self.filtered_count,
        }


def built_area(value: Any) -> float | None:
    area = (
        getattr(value, "built_area_m2", None)
        or getattr(value, "usable_area_m2", None)
        or getattr(value, "m2", None)
    )
    try:
        parsed = float(area)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def safe_price_uf(value: Any, uf_rate: Decimal | float | int) -> float | None:
    price_uf = _decimal_or_none(getattr(value, "price_uf", None))
    if price_uf is not None:
        return float(price_uf)
    price = getattr(value, "price", None)
    clp = _decimal_or_none(getattr(price, "clp", None))
    rate = _decimal_or_none(uf_rate)
    if clp is None or rate is None or rate <= 0:
        return None
    return float(clp / rate)


def safe_price_m2_uf(value: Any, uf_rate: Decimal | float | int) -> float | None:
    area = built_area(value)
    price_uf = safe_price_uf(value, uf_rate)
    if area is None or price_uf is None:
        return None
    return price_uf / area


def build_price_m2_reference(values: Sequence[float | None]) -> PriceM2Reference:
    clean = sorted(float(value) for value in values if value is not None and value > 0)
    if not clean:
        return PriceM2Reference(0, None, None, None, None, None, None)
    p10 = percentile(clean, 10)
    p25 = percentile(clean, 25)
    p75 = percentile(clean, 75)
    p90 = percentile(clean, 90)
    return PriceM2Reference(
        sample_count=len(clean),
        median=float(median(clean)),
        p10=p10,
        p25=p25,
        p75=p75,
        p90=p90,
        iqr=p75 - p25,
    )


def comparable_quality_flags(
    comparable: Any,
    *,
    uf_rate: Decimal | float | int,
    subject: Any | None = None,
    subject_price_m2_uf: float | None = None,
    comuna_median_price_m2_uf: float | None = None,
    pool_median_price_m2_uf: float | None = None,
    microzone_level: int | None = None,
    thresholds: QualityThresholds | None = None,
    now: datetime | None = None,
) -> ComparableQualityFlags:
    thresholds = thresholds or QualityThresholds()
    ppm2 = safe_price_m2_uf(comparable, uf_rate)
    subject_ppm2 = subject_price_m2_uf
    if subject_ppm2 is None and subject is not None:
        subject_ppm2 = safe_price_m2_uf(subject, uf_rate)

    flags: list[str] = []
    subject_ratio = _ratio(ppm2, subject_ppm2)
    comuna_ratio = _ratio(ppm2, comuna_median_price_m2_uf)
    pool_ratio = _ratio(ppm2, pool_median_price_m2_uf)

    if ppm2 is None:
        flags.append("missing_or_invalid_price_m2")
    _append_ratio_flags(
        flags,
        ratio=subject_ratio,
        low=thresholds.subject_low_ratio,
        high=thresholds.subject_high_ratio,
        low_flag="price_m2_too_low_vs_subject",
        high_flag="price_m2_too_high_vs_subject",
    )
    _append_ratio_flags(
        flags,
        ratio=comuna_ratio,
        low=thresholds.reference_low_ratio,
        high=thresholds.reference_high_ratio,
        low_flag="price_m2_too_low_vs_comuna_median",
        high_flag="price_m2_too_high_vs_comuna_median",
    )
    _append_ratio_flags(
        flags,
        ratio=pool_ratio,
        low=thresholds.reference_low_ratio,
        high=thresholds.reference_high_ratio,
        low_flag="price_m2_too_low_vs_pool_median",
        high_flag="price_m2_too_high_vs_pool_median",
    )

    surface_diff = surface_diff_pct(subject, comparable)
    if surface_diff is not None and surface_diff / 100 > thresholds.surface_far_ratio:
        flags.append("surface_far")

    precision = str(getattr(comparable, "geocode_precision", "") or "unknown").strip().lower()
    if precision in {"", "unknown", "comuna", "comuna_centroid"}:
        flags.append("weak_location")
    if microzone_level == 0:
        flags.append("comuna_only_location")

    if _is_stale(comparable, thresholds=thresholds, now=now):
        flags.append("stale_or_low_quality_price")
    if _missing_program(comparable):
        flags.append("missing_program")
    if subject is not None and _property_type(subject) != _property_type(comparable):
        flags.append("weak_property_type")

    economic = any(flag.startswith("price_m2_too_") for flag in flags)
    strict = _strict_outlier(
        subject_ratio=subject_ratio,
        comuna_ratio=comuna_ratio,
        pool_ratio=pool_ratio,
        thresholds=thresholds,
    )
    if economic:
        flags.append("economic_outlier")

    return ComparableQualityFlags(
        flags=tuple(_dedupe(flags)),
        price_m2_uf=ppm2,
        subject_ratio=subject_ratio,
        comuna_ratio=comuna_ratio,
        pool_ratio=pool_ratio,
        surface_diff_pct=surface_diff,
        economic_outlier=economic,
        strict_economic_outlier=strict,
    )


def surface_diff_pct(subject: Any | None, comparable: Any) -> float | None:
    if subject is None:
        return None
    subject_area = built_area(subject)
    comparable_area = built_area(comparable)
    if subject_area is None or comparable_area is None:
        return None
    return abs(comparable_area - subject_area) / subject_area * 100


def surface_similarity(subject: Any, comparable: Any) -> float:
    subject_area = built_area(subject)
    comparable_area = built_area(comparable)
    if subject_area is None or comparable_area is None:
        return 0.0
    return max(0.0, 1.0 - abs(comparable_area - subject_area) / subject_area)


def economic_similarity(
    candidate_price_m2_uf: float | None,
    reference_price_m2_uf: float | None,
) -> float:
    if candidate_price_m2_uf is None or reference_price_m2_uf is None or reference_price_m2_uf <= 0:
        return 0.5
    diff = abs(candidate_price_m2_uf - reference_price_m2_uf) / reference_price_m2_uf
    return max(0.0, 1.0 - min(diff, 1.0))


def filter_by_quality(
    scored: Sequence[tuple[float, Any]],
    flags_by_key: dict[str, ComparableQualityFlags],
    *,
    mode: str,
    key_fn,
    min_comparables: int = 5,
) -> list[tuple[float, Any]]:
    if mode not in {"mild", "strict"}:
        raise ValueError(f"unsupported mode: {mode}")
    result = []
    for score, listing in scored:
        flags = flags_by_key.get(key_fn(listing))
        if flags is None:
            result.append((score, listing))
            continue
        should_filter = flags.strict_economic_outlier if mode == "mild" else flags.economic_outlier
        if not should_filter:
            result.append((score, listing))
    if len(result) >= min_comparables:
        return result
    return list(scored)


def weighted_mean(values_and_weights: Sequence[tuple[float | None, float | None]]) -> float | None:
    total_weight = 0.0
    weighted_sum = 0.0
    for value, weight in values_and_weights:
        if value is None or value <= 0:
            continue
        clean_weight = float(weight or 0.0)
        if clean_weight <= 0:
            continue
        total_weight += clean_weight
        weighted_sum += float(value) * clean_weight
    return weighted_sum / total_weight if total_weight > 0 else None


def median_estimator(values: Sequence[float | None]) -> float | None:
    clean = _clean_values(values)
    return float(median(clean)) if clean else None


def trimmed_mean_estimator(values: Sequence[float | None], *, trim_ratio: float = 0.10) -> float | None:
    clean = _clean_values(values)
    if not clean:
        return None
    cut = int(len(clean) * trim_ratio)
    trimmed = clean[cut : len(clean) - cut] if cut > 0 and len(clean) - 2 * cut >= 1 else clean
    return float(mean(trimmed))


def winsorized_mean_estimator(values: Sequence[float | None], *, winsor_ratio: float = 0.10) -> float | None:
    clean = _clean_values(values)
    if not clean:
        return None
    cut = int(len(clean) * winsor_ratio)
    if cut <= 0:
        return float(mean(clean))
    low = clean[cut]
    high = clean[-cut - 1]
    winsorized = [min(max(value, low), high) for value in clean]
    return float(mean(winsorized))


def weighted_median(values_and_weights: Sequence[tuple[float | None, float | None]]) -> float | None:
    pairs = sorted(
        (float(value), float(weight or 0.0))
        for value, weight in values_and_weights
        if value is not None and value > 0 and weight is not None and weight > 0
    )
    if not pairs:
        return None
    total = sum(weight for _, weight in pairs)
    midpoint = total / 2
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += weight
        if cumulative >= midpoint:
            return value
    return pairs[-1][0]


def percentile(values: Sequence[float], pct: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * pct / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _clean_values(values: Sequence[float | None]) -> list[float]:
    return sorted(float(value) for value in values if value is not None and value > 0)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed > 0 else None


def _ratio(value: float | None, reference: float | None) -> float | None:
    if value is None or reference is None or reference <= 0:
        return None
    return value / reference


def _append_ratio_flags(
    flags: list[str],
    *,
    ratio: float | None,
    low: float,
    high: float,
    low_flag: str,
    high_flag: str,
) -> None:
    if ratio is None:
        return
    if ratio < low:
        flags.append(low_flag)
    elif ratio > high:
        flags.append(high_flag)


def _strict_outlier(
    *,
    subject_ratio: float | None,
    comuna_ratio: float | None,
    pool_ratio: float | None,
    thresholds: QualityThresholds,
) -> bool:
    ratios = [ratio for ratio in (subject_ratio, comuna_ratio, pool_ratio) if ratio is not None]
    if not ratios:
        return False
    return any(
        ratio < thresholds.strict_reference_low_ratio or ratio > thresholds.strict_reference_high_ratio
        for ratio in ratios
    )


def _is_stale(value: Any, *, thresholds: QualityThresholds, now: datetime | None) -> bool:
    ref = getattr(value, "last_seen_at", None) or getattr(value, "scraped_at", None)
    if ref is None:
        return False
    if now is None:
        now = datetime.now(UTC)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=UTC)
    return (now - ref).days > thresholds.stale_days


def _missing_program(value: Any) -> bool:
    return any(getattr(value, attr, None) is None for attr in ("bedrooms", "bathrooms", "parking"))


def _property_type(value: Any) -> str:
    return str(getattr(value, "property_type", "") or "unknown").strip().lower()


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(float(value), digits) if value is not None else None
