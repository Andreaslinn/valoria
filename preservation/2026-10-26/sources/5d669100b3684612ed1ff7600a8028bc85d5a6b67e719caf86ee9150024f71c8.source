"""Conservative price surface diagnostics for valuation.

Price surfaces are auxiliary market statistics. They do not replace the
comparables engine and must not imply precise geocoding.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import median
from typing import Any

from core.entities.listing import Listing, Property
from core.normalization.property_type import normalize_property_type as _property_type
from domain.geocoding.microzones import signals_from_value

DEFAULT_MIN_SURFACE_SAMPLES = 5
DEFAULT_PRICE_SURFACE_CACHE_TTL_SECONDS = 300.0
HIGH_DISPERSION_PCT = 45.0
MATERIAL_DIFF_PCT = 25.0
DEFAULT_RISK_COMUNAS = frozenset({"vitacura"})
DEFAULT_RISK_M2_BUCKETS = frozenset({"40-59"})
DEFAULT_HISTORICAL_SURFACE_WIN_RATE_BY_LEVEL = {
    "microzone_m2_bucket": 63.64,
    "comuna_m2_bucket": 48.73,
    "comuna": 40.0,
}

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PriceSurfaceStats:
    median_price_m2: float
    p25_price_m2: float
    p75_price_m2: float
    iqr: float
    sample_count: int
    dispersion: float
    confidence: float


@dataclass(frozen=True)
class PriceSurfaceResult:
    available: bool
    level_used: str
    stats: PriceSurfaceStats | None
    microzone_token: str | None = None
    reason: str | None = None

    @property
    def surface_price_m2(self) -> float | None:
        return self.stats.median_price_m2 if self.stats else None

    @property
    def surface_dispersion(self) -> float | None:
        return self.stats.dispersion if self.stats else None


@dataclass(frozen=True)
class SegmentAdjustmentPolicy:
    name: str
    property_type: str | None = None
    comuna: str | None = None
    m2_bucket: str | None = None
    surface_level_used: str | None = None
    allow_adjustment: bool | None = None
    adjustment_weight: float | None = None
    max_weight: float | None = None
    min_sample_count: int | None = None
    min_comuna_bucket_sample_count: int | None = None
    max_microzone_dispersion: float | None = None
    max_comuna_bucket_dispersion: float | None = None
    warning: str | None = None


DEFAULT_SEGMENT_ADJUSTMENT_POLICIES = (
    SegmentAdjustmentPolicy(
        name="comuna_only_no_adjust",
        surface_level_used="comuna",
        allow_adjustment=False,
        warning="surface_adjustment_comuna_only",
    ),
    SegmentAdjustmentPolicy(
        name="vitacura_no_adjust",
        comuna="vitacura",
        allow_adjustment=False,
        warning="surface_adjustment_risk_comuna",
    ),
    SegmentAdjustmentPolicy(
        name="small_m2_bucket_no_adjust",
        m2_bucket="40-59",
        allow_adjustment=False,
        warning="surface_adjustment_risk_m2_bucket",
    ),
    SegmentAdjustmentPolicy(
        name="san_miguel_15pct",
        comuna="san_miguel",
        adjustment_weight=0.15,
        max_weight=0.15,
    ),
    SegmentAdjustmentPolicy(
        name="microzone_m2_bucket_20pct_cap",
        surface_level_used="microzone_m2_bucket",
        max_weight=0.20,
    ),
)


@dataclass(frozen=True)
class SurfaceAdjustmentConfig:
    min_sample_count: int = 10
    min_comuna_bucket_sample_count: int = 20
    default_weight: float = 0.10
    strong_weight: float = 0.20
    max_weight: float = 0.20
    max_moderate_dispersion: float = 35.0
    max_microzone_dispersion: float = 50.0
    max_comuna_bucket_dispersion: float = 75.0
    historical_win_rate_threshold: float = 55.0
    risk_comunas: frozenset[str] = DEFAULT_RISK_COMUNAS
    risk_m2_buckets: frozenset[str] = DEFAULT_RISK_M2_BUCKETS
    historical_win_rate_by_level: dict[str, float] | None = None
    segment_policies: tuple[SegmentAdjustmentPolicy, ...] = DEFAULT_SEGMENT_ADJUSTMENT_POLICIES


@dataclass(frozen=True)
class SurfaceAdjustmentResult:
    adjusted_estimate: float
    adjustment_applied: bool
    adjustment_weight: float
    adjustment_reason: str
    warnings: list[str]


@dataclass(frozen=True)
class PriceSurfaceIndex:
    by_comuna: dict[tuple[str, str], PriceSurfaceStats]
    by_comuna_bucket: dict[tuple[str, str, str], PriceSurfaceStats]
    by_microzone: dict[tuple[str, str, str], PriceSurfaceStats]
    by_microzone_bucket: dict[tuple[str, str, str, str], PriceSurfaceStats]
    insufficient_segments: Counter[str]

    def lookup(self, target: Property | Listing) -> PriceSurfaceResult:
        property_type = _property_type(target)
        comuna = _optional_str(getattr(target, "comuna", None))
        if not comuna:
            return PriceSurfaceResult(False, "insufficient_data", None, reason="missing_comuna")
        bucket = m2_bucket_for(target)
        tokens = microzone_tokens_for(target)

        for token in tokens:
            stats = self.by_microzone_bucket.get((property_type, comuna, token, bucket))
            if stats is not None:
                return PriceSurfaceResult(True, "microzone_m2_bucket", stats, token)
        for token in tokens:
            stats = self.by_microzone.get((property_type, comuna, token))
            if stats is not None:
                return PriceSurfaceResult(True, "microzone", stats, token)

        stats = self.by_comuna_bucket.get((property_type, comuna, bucket))
        if stats is not None:
            return PriceSurfaceResult(True, "comuna_m2_bucket", stats)

        stats = self.by_comuna.get((property_type, comuna))
        if stats is not None:
            return PriceSurfaceResult(True, "comuna", stats)

        return PriceSurfaceResult(False, "insufficient_data", None, reason="insufficient_samples")


@dataclass(frozen=True)
class _PriceSurfaceCacheEntry:
    signature: tuple[Any, ...]
    min_samples: int
    expires_at: float
    index: PriceSurfaceIndex


class PriceSurfaceIndexCache:
    """Tiny per-process cache for price surface indexes."""

    def __init__(self, *, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._entry: _PriceSurfaceCacheEntry | None = None

    def get(
        self,
        listings: Sequence[Listing],
        *,
        min_samples: int = DEFAULT_MIN_SURFACE_SAMPLES,
        ttl_seconds: float = DEFAULT_PRICE_SURFACE_CACHE_TTL_SECONDS,
    ) -> PriceSurfaceIndex:
        if ttl_seconds <= 0:
            _log.info("price_surface_index_rebuild reason=cache_disabled")
            return build_price_surface_index(listings, min_samples=min_samples)

        signature = _surface_cache_signature(listings)
        now = self._clock()
        with self._lock:
            if (
                self._entry is not None
                and self._entry.min_samples == min_samples
                and self._entry.signature == signature
                and self._entry.expires_at > now
            ):
                return self._entry.index

            reason = _cache_rebuild_reason(self._entry, signature, min_samples, now)
            _log.info(
                "price_surface_index_rebuild reason=%s active_count=%s min_samples=%s ttl_seconds=%s",
                reason,
                signature[0],
                min_samples,
                ttl_seconds,
            )
            index = build_price_surface_index(listings, min_samples=min_samples)
            self._entry = _PriceSurfaceCacheEntry(
                signature=signature,
                min_samples=min_samples,
                expires_at=now + ttl_seconds,
                index=index,
            )
            return index

    def clear(self) -> None:
        with self._lock:
            self._entry = None


_DEFAULT_PRICE_SURFACE_CACHE = PriceSurfaceIndexCache()


def build_price_surface_index(
    listings: Sequence[Listing],
    *,
    min_samples: int = DEFAULT_MIN_SURFACE_SAMPLES,
) -> PriceSurfaceIndex:
    groups_comuna: dict[tuple[str, str], list[float]] = defaultdict(list)
    groups_comuna_bucket: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    groups_microzone: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    groups_microzone_bucket: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)

    for listing in listings:
        price_m2 = price_per_m2(listing)
        comuna = _optional_str(listing.comuna)
        if price_m2 is None or not comuna or not listing.is_active:
            continue
        property_type = _property_type(listing)
        bucket = m2_bucket_for(listing)
        groups_comuna[(property_type, comuna)].append(price_m2)
        groups_comuna_bucket[(property_type, comuna, bucket)].append(price_m2)
        for token in microzone_tokens_for(listing):
            groups_microzone[(property_type, comuna, token)].append(price_m2)
            groups_microzone_bucket[(property_type, comuna, token, bucket)].append(price_m2)

    insufficient = Counter()
    return PriceSurfaceIndex(
        by_comuna=_materialize(groups_comuna, min_samples=min_samples, label="comuna", insufficient=insufficient),
        by_comuna_bucket=_materialize(
            groups_comuna_bucket,
            min_samples=min_samples,
            label="comuna_m2_bucket",
            insufficient=insufficient,
        ),
        by_microzone=_materialize(
            groups_microzone,
            min_samples=min_samples,
            label="microzone",
            insufficient=insufficient,
        ),
        by_microzone_bucket=_materialize(
            groups_microzone_bucket,
            min_samples=min_samples,
            label="microzone_m2_bucket",
            insufficient=insufficient,
        ),
        insufficient_segments=insufficient,
    )


def lookup_price_surface(
    target: Property | Listing,
    listings: Sequence[Listing],
    *,
    min_samples: int = DEFAULT_MIN_SURFACE_SAMPLES,
    cache_ttl_seconds: float = DEFAULT_PRICE_SURFACE_CACHE_TTL_SECONDS,
    cache: PriceSurfaceIndexCache | None = None,
) -> PriceSurfaceResult:
    index_cache = cache or _DEFAULT_PRICE_SURFACE_CACHE
    return index_cache.get(
        listings,
        min_samples=min_samples,
        ttl_seconds=cache_ttl_seconds,
    ).lookup(target)


def clear_price_surface_cache() -> None:
    _DEFAULT_PRICE_SURFACE_CACHE.clear()


def maybe_apply_surface_adjustment(
    base_estimate: float | Decimal,
    surface_context: PriceSurfaceResult | dict[str, Any],
    property_data: Property | Listing | dict[str, Any],
    config: SurfaceAdjustmentConfig | None = None,
) -> SurfaceAdjustmentResult:
    config = config or SurfaceAdjustmentConfig(
        historical_win_rate_by_level=DEFAULT_HISTORICAL_SURFACE_WIN_RATE_BY_LEVEL
    )
    base = float(base_estimate)
    context = _surface_context_dict(surface_context)
    warnings: list[str] = []
    if base <= 0:
        return SurfaceAdjustmentResult(base, False, 0.0, "invalid_base_estimate", ["surface_adjustment_invalid_base"])
    if not context["available"] or context["surface_price_m2"] is None:
        return SurfaceAdjustmentResult(base, False, 0.0, "surface_unavailable", ["surface_adjustment_unavailable"])

    surface_level = str(context["level_used"] or "unknown")
    sample_count = int(context["sample_count"] or 0)
    dispersion = context["dispersion"]
    area = _built_area_from_any(property_data)
    comuna = _normal_text(_get_any(property_data, "comuna"))
    property_type = _property_type(_get_any(property_data, "property_type"))
    bucket = str(_get_any(property_data, "m2_bucket") or m2_bucket(area))
    effective_default_weight = config.default_weight
    effective_max_weight = config.max_weight
    effective_min_sample_count = config.min_sample_count
    effective_min_comuna_bucket_sample_count = config.min_comuna_bucket_sample_count
    effective_max_microzone_dispersion = config.max_microzone_dispersion
    effective_max_comuna_bucket_dispersion = config.max_comuna_bucket_dispersion
    matched_policy_names: list[str] = []

    for policy in _matching_segment_policies(
        config,
        property_type=property_type,
        comuna=comuna,
        m2_bucket=bucket,
        surface_level_used=surface_level,
    ):
        matched_policy_names.append(policy.name)
        if policy.warning:
            warnings.append(policy.warning)
        if policy.allow_adjustment is False:
            return SurfaceAdjustmentResult(
                base,
                False,
                0.0,
                f"policy:{policy.name}",
                warnings,
            )
        if policy.adjustment_weight is not None:
            effective_default_weight = policy.adjustment_weight
        if policy.max_weight is not None:
            effective_max_weight = policy.max_weight
        if policy.min_sample_count is not None:
            effective_min_sample_count = policy.min_sample_count
        if policy.min_comuna_bucket_sample_count is not None:
            effective_min_comuna_bucket_sample_count = policy.min_comuna_bucket_sample_count
        if policy.max_microzone_dispersion is not None:
            effective_max_microzone_dispersion = policy.max_microzone_dispersion
        if policy.max_comuna_bucket_dispersion is not None:
            effective_max_comuna_bucket_dispersion = policy.max_comuna_bucket_dispersion

    if sample_count < effective_min_sample_count:
        return SurfaceAdjustmentResult(base, False, 0.0, "sample_count_below_threshold", ["surface_adjustment_low_sample"])
    if surface_level == "comuna":
        return SurfaceAdjustmentResult(base, False, 0.0, "comuna_only_surface", ["surface_adjustment_comuna_only"])
    if comuna in config.risk_comunas:
        return SurfaceAdjustmentResult(base, False, 0.0, "risk_comuna", ["surface_adjustment_risk_comuna"])
    if bucket in config.risk_m2_buckets:
        return SurfaceAdjustmentResult(base, False, 0.0, "risk_m2_bucket", ["surface_adjustment_risk_m2_bucket"])
    if area is None or area <= 0:
        return SurfaceAdjustmentResult(base, False, 0.0, "missing_area", ["surface_adjustment_missing_area"])
    if surface_level == "comuna_m2_bucket" and sample_count < effective_min_comuna_bucket_sample_count:
        return SurfaceAdjustmentResult(
            base,
            False,
            0.0,
            "comuna_bucket_sample_count_below_threshold",
            ["surface_adjustment_weak_comuna_bucket"],
        )
    if surface_level in {"microzone", "microzone_m2_bucket"} and (
        dispersion is None or dispersion > effective_max_microzone_dispersion
    ):
        return SurfaceAdjustmentResult(
            base,
            False,
            0.0,
            "microzone_dispersion_too_high",
            ["surface_adjustment_high_microzone_dispersion"],
        )
    if surface_level not in {"microzone", "microzone_m2_bucket", "comuna_m2_bucket"}:
        return SurfaceAdjustmentResult(
            base,
            False,
            0.0,
            "unsupported_surface_level",
            ["surface_adjustment_unsupported_level"],
        )

    if dispersion is not None and dispersion >= HIGH_DISPERSION_PCT:
        warnings.append("surface_adjustment_high_dispersion")

    weight = min(effective_default_weight, effective_max_weight)
    reason = _adjustment_reason("default_surface_adjustment", matched_policy_names)
    historical = _historical_win_rate(surface_level, config)
    if (
        surface_level == "microzone_m2_bucket"
        and sample_count >= 20
        and dispersion is not None
        and dispersion <= config.max_moderate_dispersion
        and (historical is None or historical > config.historical_win_rate_threshold)
    ):
        weight = min(config.strong_weight, effective_max_weight)
        reason = _adjustment_reason("strong_microzone_surface_adjustment", matched_policy_names)
    elif historical is not None and historical <= config.historical_win_rate_threshold and surface_level == "microzone_m2_bucket":
        warnings.append("surface_adjustment_historical_win_rate_not_strong")

    surface_estimate = float(context["surface_price_m2"]) * area
    adjusted = base * (1.0 - weight) + surface_estimate * weight
    return SurfaceAdjustmentResult(
        adjusted_estimate=round(adjusted, 2),
        adjustment_applied=weight > 0,
        adjustment_weight=round(weight, 3),
        adjustment_reason=reason,
        warnings=warnings,
    )


def surface_warnings_for_estimate(
    *,
    estimated_price_m2: float | None,
    surface: PriceSurfaceResult,
) -> list[str]:
    if not surface.available or surface.stats is None:
        return ["price_surface_insufficient_data"]
    warnings: list[str] = []
    if surface.stats.confidence < 0.45:
        warnings.append("price_surface_low_confidence")
    if surface.stats.dispersion >= HIGH_DISPERSION_PCT:
        warnings.append("price_surface_high_dispersion")
    if estimated_price_m2 is not None and surface.stats.median_price_m2 > 0:
        diff_pct = abs(estimated_price_m2 - surface.stats.median_price_m2) / surface.stats.median_price_m2 * 100
        if diff_pct >= MATERIAL_DIFF_PCT:
            warnings.append("estimate_differs_from_price_surface")
    return warnings


def price_surface_diagnostics(
    listings: Sequence[Listing],
    *,
    min_samples: int = DEFAULT_MIN_SURFACE_SAMPLES,
    limit: int = 20,
) -> dict[str, Any]:
    index = build_price_surface_index(listings, min_samples=min_samples)
    top_microzones = sorted(
        (
            {
                "property_type": key[0],
                "comuna": key[1],
                "microzone_token": key[2],
                "sample_count": stats.sample_count,
                "median_price_m2": round(stats.median_price_m2, 2),
                "dispersion": round(stats.dispersion, 2),
                "confidence": stats.confidence,
            }
            for key, stats in index.by_microzone.items()
        ),
        key=lambda row: (-row["sample_count"], row["property_type"], row["comuna"], row["microzone_token"]),
    )[:limit]
    high_dispersion = sorted(
        (
            {
                "property_type": key[0],
                "comuna": key[1],
                "sample_count": stats.sample_count,
                "dispersion": round(stats.dispersion, 2),
                "median_price_m2": round(stats.median_price_m2, 2),
            }
            for key, stats in index.by_comuna.items()
            if stats.dispersion >= HIGH_DISPERSION_PCT
        ),
        key=lambda row: -row["dispersion"],
    )[:limit]
    return {
        "top_microzones": top_microzones,
        "high_dispersion_comunas": high_dispersion,
        "insufficient_segments": dict(index.insufficient_segments),
    }


def microzone_tokens_for(value: Property | Listing) -> tuple[str, ...]:
    signals = signals_from_value(value)
    if signals.confidence < 0.55:
        return ()
    tokens = {str(token) for token in signals.landmark_tokens if str(token).strip()}
    return tuple(sorted(tokens, key=_token_priority))


def _token_priority(token: str) -> tuple[int, str]:
    prefix = token.split(":", 1)[0]
    priority = {
        "intersection": 0,
        "metro": 1,
        "avenue": 2,
        "landmark": 3,
    }.get(prefix, 9)
    return priority, token


def price_per_m2(listing: Listing) -> float | None:
    area = _built_area(listing)
    if area is None or area <= 0 or listing.price.clp <= 0:
        return None
    return float(listing.price.clp) / float(area)


def m2_bucket_for(value: Property | Listing) -> str:
    return m2_bucket(_built_area(value))


def m2_bucket(area: float | None) -> str:
    if area is None or area <= 0:
        return "unknown"
    if area < 40:
        return "0-39"
    if area < 60:
        return "40-59"
    if area < 80:
        return "60-79"
    if area < 120:
        return "80-119"
    if area < 180:
        return "120-179"
    return "180+"


def _materialize(
    groups: dict[Any, list[float]],
    *,
    min_samples: int,
    label: str,
    insufficient: Counter[str],
) -> dict[Any, PriceSurfaceStats]:
    materialized: dict[Any, PriceSurfaceStats] = {}
    for key, values in groups.items():
        if len(values) < min_samples:
            insufficient[label] += 1
            continue
        materialized[key] = calculate_price_surface_stats(values)
    return materialized


def _surface_cache_signature(listings: Sequence[Listing]) -> tuple[Any, ...]:
    active_keys: list[str] = []
    latest_timestamp: float | None = None
    for listing in listings:
        if not listing.is_active:
            continue
        active_keys.append(_listing_cache_key(listing))
        timestamp = _timestamp_value(
            getattr(listing, "updated_at", None)
            or getattr(listing, "scraped_at", None)
            or _metadata_timestamp(listing)
        )
        if timestamp is not None:
            latest_timestamp = timestamp if latest_timestamp is None else max(latest_timestamp, timestamp)
    active_keys.sort()
    return (len(active_keys), latest_timestamp, tuple(active_keys))


def _listing_cache_key(listing: Listing) -> str:
    if listing.id is not None:
        return f"id:{listing.id}"
    if listing.fingerprint:
        return f"fp:{listing.fingerprint}"
    if listing.external_id:
        return f"ext:{listing.source}:{listing.external_id}"
    return f"obj:{id(listing)}"


def _metadata_timestamp(listing: Listing) -> Any | None:
    metadata = getattr(listing, "raw_metadata", None)
    if not isinstance(metadata, dict):
        return None
    return (
        metadata.get("updated_at")
        or metadata.get("last_updated_at")
        or metadata.get("scraped_at")
    )


def _timestamp_value(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _cache_rebuild_reason(
    entry: _PriceSurfaceCacheEntry | None,
    signature: tuple[Any, ...],
    min_samples: int,
    now: float,
) -> str:
    if entry is None:
        return "empty"
    if entry.min_samples != min_samples:
        return "min_samples_changed"
    if entry.expires_at <= now:
        return "ttl_expired"
    if entry.signature[0] != signature[0]:
        return "active_count_changed"
    if entry.signature[1] != signature[1]:
        return "latest_timestamp_changed"
    if entry.signature[2] != signature[2]:
        return "listing_set_changed"
    return "signature_changed"


def calculate_price_surface_stats(values: Iterable[float | Decimal]) -> PriceSurfaceStats:
    clean = sorted(float(value) for value in values if value is not None and float(value) > 0)
    if not clean:
        raise ValueError("price surface requires at least one positive price/m2")
    p25 = _percentile(clean, 25)
    p75 = _percentile(clean, 75)
    med = float(median(clean))
    iqr = p75 - p25
    dispersion = (iqr / med * 100) if med > 0 else 100.0
    return PriceSurfaceStats(
        median_price_m2=round(med, 2),
        p25_price_m2=round(p25, 2),
        p75_price_m2=round(p75, 2),
        iqr=round(iqr, 2),
        sample_count=len(clean),
        dispersion=round(dispersion, 2),
        confidence=_surface_confidence(len(clean), dispersion),
    )


def _surface_confidence(sample_count: int, dispersion: float) -> float:
    sample_factor = min(1.0, sample_count / 20.0)
    dispersion_factor = max(0.15, 1.0 - min(1.0, dispersion / 80.0))
    return round(sample_factor * dispersion_factor, 3)


def _percentile(values: Sequence[float], percentile: int) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (percentile / 100)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _built_area(value: Property | Listing) -> float | None:
    return getattr(value, "built_area_m2", None) or getattr(value, "usable_area_m2", None) or value.m2


def _built_area_from_any(value: Property | Listing | dict[str, Any]) -> float | None:
    if isinstance(value, dict):
        for key in ("built_area_m2", "usable_area_m2", "m2", "area_m2"):
            raw = value.get(key)
            if raw is not None:
                try:
                    parsed = float(raw)
                except (TypeError, ValueError):
                    continue
                if parsed > 0:
                    return parsed
        return None
    return _built_area(value)


def _surface_context_dict(surface_context: PriceSurfaceResult | dict[str, Any]) -> dict[str, Any]:
    if isinstance(surface_context, PriceSurfaceResult):
        return {
            "available": surface_context.available,
            "level_used": surface_context.level_used,
            "surface_price_m2": surface_context.surface_price_m2,
            "dispersion": surface_context.surface_dispersion,
            "sample_count": surface_context.stats.sample_count if surface_context.stats else None,
        }
    return {
        "available": bool(surface_context.get("available", surface_context.get("surface_available", False))),
        "level_used": surface_context.get("level_used") or surface_context.get("surface_level_used"),
        "surface_price_m2": surface_context.get("surface_price_m2"),
        "dispersion": surface_context.get("dispersion") or surface_context.get("surface_dispersion"),
        "sample_count": surface_context.get("sample_count") or surface_context.get("surface_sample_count"),
    }


def _get_any(value: Property | Listing | dict[str, Any], key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _normal_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _historical_win_rate(level: str, config: SurfaceAdjustmentConfig) -> float | None:
    rates = config.historical_win_rate_by_level
    if rates is None:
        rates = DEFAULT_HISTORICAL_SURFACE_WIN_RATE_BY_LEVEL
    value = rates.get(level)
    return float(value) if value is not None else None


def _matching_segment_policies(
    config: SurfaceAdjustmentConfig,
    *,
    property_type: str,
    comuna: str,
    m2_bucket: str,
    surface_level_used: str,
) -> list[SegmentAdjustmentPolicy]:
    return [
        policy
        for policy in config.segment_policies
        if _policy_matches(
            policy,
            property_type=property_type,
            comuna=comuna,
            m2_bucket=m2_bucket,
            surface_level_used=surface_level_used,
        )
    ]


def _policy_matches(
    policy: SegmentAdjustmentPolicy,
    *,
    property_type: str,
    comuna: str,
    m2_bucket: str,
    surface_level_used: str,
) -> bool:
    return all(
        (
            policy.property_type is None or _normal_text(policy.property_type) == property_type,
            policy.comuna is None or _normal_text(policy.comuna) == comuna,
            policy.m2_bucket is None or str(policy.m2_bucket) == m2_bucket,
            policy.surface_level_used is None or str(policy.surface_level_used) == surface_level_used,
        )
    )


def _adjustment_reason(base_reason: str, policy_names: Sequence[str]) -> str:
    if not policy_names:
        return base_reason
    return f"{base_reason}|policies:{','.join(policy_names)}"


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
