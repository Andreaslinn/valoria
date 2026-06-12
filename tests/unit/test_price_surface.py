from __future__ import annotations

from datetime import UTC, datetime, timedelta

import domain.valuation.price_surface as price_surface_module
from domain.geocoding.microzones import extract_microzone_signals
from domain.valuation.price_surface import (
    PriceSurfaceResult,
    PriceSurfaceIndexCache,
    PriceSurfaceStats,
    SegmentAdjustmentPolicy,
    SurfaceAdjustmentConfig,
    build_price_surface_index,
    clear_price_surface_cache,
    calculate_price_surface_stats,
    lookup_price_surface,
    maybe_apply_surface_adjustment,
    surface_warnings_for_estimate,
)
from tests.unit.factories import make_listing, make_property


def _signals(title: str) -> dict:
    return {"geo_signals": extract_microzone_signals(title=title).as_dict()}


class _Clock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


def test_calculates_median_p25_p75_and_dispersion() -> None:
    stats = calculate_price_surface_stats([100, 200, 300, 400, 500])

    assert stats.median_price_m2 == 300
    assert stats.p25_price_m2 == 200
    assert stats.p75_price_m2 == 400
    assert stats.iqr == 200
    assert stats.sample_count == 5
    assert stats.dispersion == 66.67
    assert 0.0 <= stats.confidence <= 1.0


def test_uses_microzone_m2_bucket_when_enough_samples() -> None:
    listings = [
        make_listing(
            fingerprint=f"metro-{idx}",
            comuna="santiago",
            m2=75,
            price_clp=150_000_000 + idx * 1_000_000,
            raw_metadata=_signals("Metro Parque Almagro"),
        )
        for idx in range(5)
    ]
    target = make_property(comuna="santiago", m2=75, raw_metadata=_signals("Metro Parque Almagro"))

    result = lookup_price_surface(target, listings)

    assert result.available
    assert result.level_used == "microzone_m2_bucket"
    assert result.microzone_token == "metro:parque almagro"
    assert result.stats is not None
    assert result.stats.sample_count == 5


def test_microzone_with_low_sample_count_falls_back_to_comuna_bucket() -> None:
    microzone = [
        make_listing(
            fingerprint=f"thin-{idx}",
            comuna="santiago",
            m2=75,
            price_clp=150_000_000,
            raw_metadata=_signals("Metro Parque Almagro"),
        )
        for idx in range(4)
    ]
    comuna = [
        make_listing(fingerprint=f"plain-{idx}", comuna="santiago", m2=75, price_clp=160_000_000)
        for idx in range(5)
    ]
    target = make_property(comuna="santiago", m2=75, raw_metadata=_signals("Metro Parque Almagro"))

    result = lookup_price_surface(target, [*microzone, *comuna])

    assert result.available
    assert result.level_used == "comuna_m2_bucket"
    assert result.microzone_token is None


def test_insufficient_when_all_segments_are_below_min_samples() -> None:
    listings = [
        make_listing(fingerprint=f"few-{idx}", comuna="santiago", m2=75, price_clp=150_000_000)
        for idx in range(4)
    ]
    target = make_property(comuna="santiago", m2=75)

    result = lookup_price_surface(target, listings)

    assert not result.available
    assert result.level_used == "insufficient_data"


def test_does_not_mix_houses_and_apartments() -> None:
    apartments = [
        make_listing(
            fingerprint=f"apt-{idx}",
            comuna="nunoa",
            property_type="apartment",
            m2=75,
            price_clp=150_000_000,
        )
        for idx in range(10)
    ]
    houses = [
        make_listing(
            fingerprint=f"house-{idx}",
            comuna="nunoa",
            property_type="house",
            m2=75,
            built_area_m2=75,
            land_area_m2=300,
            price_clp=900_000_000,
        )
        for idx in range(5)
    ]
    target = make_property(comuna="nunoa", property_type="apartment", m2=75)

    result = lookup_price_surface(target, [*apartments, *houses])

    assert result.available
    assert result.surface_price_m2 == 2_000_000


def test_does_not_mix_comunas() -> None:
    nunoa = [
        make_listing(fingerprint=f"nu-{idx}", comuna="nunoa", m2=75, price_clp=150_000_000)
        for idx in range(5)
    ]
    providencia = [
        make_listing(fingerprint=f"pro-{idx}", comuna="providencia", m2=75, price_clp=300_000_000)
        for idx in range(5)
    ]
    target = make_property(comuna="nunoa", m2=75)

    result = lookup_price_surface(target, [*nunoa, *providencia])

    assert result.available
    assert result.surface_price_m2 == 2_000_000


def test_price_surface_cache_reuses_index_within_ttl() -> None:
    clock = _Clock()
    cache = PriceSurfaceIndexCache(clock=clock)
    listings = [
        make_listing(fingerprint=f"cache-{idx}", comuna="nunoa", m2=75, price_clp=150_000_000)
        for idx in range(5)
    ]

    first = cache.get(listings, ttl_seconds=300)
    second = cache.get(listings, ttl_seconds=300)

    assert first is second


def test_price_surface_cache_rebuilds_after_ttl() -> None:
    clock = _Clock()
    cache = PriceSurfaceIndexCache(clock=clock)
    listings = [
        make_listing(fingerprint=f"cache-ttl-{idx}", comuna="nunoa", m2=75, price_clp=150_000_000)
        for idx in range(5)
    ]

    first = cache.get(listings, ttl_seconds=300)
    clock.value += 301
    second = cache.get(listings, ttl_seconds=300)

    assert first is not second


def test_price_surface_cache_rebuilds_when_active_count_changes() -> None:
    clock = _Clock()
    cache = PriceSurfaceIndexCache(clock=clock)
    listings = [
        make_listing(fingerprint=f"cache-count-{idx}", comuna="nunoa", m2=75, price_clp=150_000_000)
        for idx in range(5)
    ]

    first = cache.get(listings, ttl_seconds=300)
    second = cache.get([*listings, make_listing(fingerprint="cache-count-new")], ttl_seconds=300)

    assert first is not second


def test_price_surface_cache_rebuilds_when_latest_timestamp_changes() -> None:
    clock = _Clock()
    cache = PriceSurfaceIndexCache(clock=clock)
    listings = [
        make_listing(fingerprint=f"cache-time-{idx}", comuna="nunoa", m2=75, price_clp=150_000_000)
        for idx in range(5)
    ]
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for listing in listings:
        listing.scraped_at = base

    first = cache.get(listings, ttl_seconds=300)
    listings[-1].scraped_at = base + timedelta(minutes=5)
    second = cache.get(listings, ttl_seconds=300)

    assert first is not second


def test_lookup_price_surface_can_disable_cache(monkeypatch) -> None:
    calls = {"count": 0}
    original = price_surface_module.build_price_surface_index
    listings = [
        make_listing(fingerprint=f"cache-disabled-{idx}", comuna="nunoa", m2=75, price_clp=150_000_000)
        for idx in range(5)
    ]
    target = make_property(comuna="nunoa", m2=75)

    def counting_build(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(price_surface_module, "build_price_surface_index", counting_build)
    clear_price_surface_cache()

    lookup_price_surface(target, listings, cache_ttl_seconds=0)
    lookup_price_surface(target, listings, cache_ttl_seconds=0)

    assert calls["count"] == 2


def test_surface_warning_when_estimate_differs_materially() -> None:
    listings = [
        make_listing(fingerprint=f"base-{idx}", comuna="nunoa", m2=75, price_clp=150_000_000)
        for idx in range(5)
    ]
    surface = build_price_surface_index(listings).lookup(make_property(comuna="nunoa", m2=75))

    warnings = surface_warnings_for_estimate(estimated_price_m2=3_000_000, surface=surface)

    assert "estimate_differs_from_price_surface" in warnings


def _surface(
    *,
    level: str = "comuna_m2_bucket",
    sample_count: int = 20,
    dispersion: float = 25.0,
    price_m2: float = 2_200_000,
) -> PriceSurfaceResult:
    return PriceSurfaceResult(
        available=True,
        level_used=level,
        stats=PriceSurfaceStats(
            median_price_m2=price_m2,
            p25_price_m2=price_m2 * 0.9,
            p75_price_m2=price_m2 * 1.1,
            iqr=price_m2 * 0.2,
            sample_count=sample_count,
            dispersion=dispersion,
            confidence=0.7,
        ),
    )


def test_surface_adjustment_does_not_apply_when_sample_count_is_low() -> None:
    result = maybe_apply_surface_adjustment(
        150_000_000,
        _surface(sample_count=9),
        {"comuna": "nunoa", "m2": 75, "property_type": "apartment"},
    )

    assert not result.adjustment_applied
    assert result.adjustment_reason == "sample_count_below_threshold"


def test_surface_adjustment_does_not_apply_to_comuna_only_surface() -> None:
    result = maybe_apply_surface_adjustment(
        150_000_000,
        _surface(level="comuna", sample_count=50),
        {"comuna": "nunoa", "m2": 75, "property_type": "apartment"},
    )

    assert not result.adjustment_applied
    assert result.adjustment_reason == "policy:comuna_only_no_adjust"


def test_surface_adjustment_does_not_apply_to_vitacura() -> None:
    result = maybe_apply_surface_adjustment(
        150_000_000,
        _surface(sample_count=50),
        {"comuna": "vitacura", "m2": 75, "property_type": "apartment"},
    )

    assert not result.adjustment_applied
    assert result.adjustment_reason == "policy:vitacura_no_adjust"


def test_surface_adjustment_does_not_apply_to_40_59_m2_bucket() -> None:
    result = maybe_apply_surface_adjustment(
        100_000_000,
        _surface(sample_count=50),
        {"comuna": "nunoa", "m2": 45, "property_type": "apartment"},
    )

    assert not result.adjustment_applied
    assert result.adjustment_reason == "policy:small_m2_bucket_no_adjust"


def test_surface_adjustment_applies_10_pct_for_reliable_surface() -> None:
    result = maybe_apply_surface_adjustment(
        150_000_000,
        _surface(level="comuna_m2_bucket", sample_count=20, price_m2=2_200_000),
        {"comuna": "nunoa", "m2": 75, "property_type": "apartment"},
    )

    assert result.adjustment_applied
    assert result.adjustment_weight == 0.1
    assert result.adjusted_estimate == 151_500_000


def test_surface_adjustment_does_not_apply_to_weak_comuna_bucket() -> None:
    result = maybe_apply_surface_adjustment(
        150_000_000,
        _surface(level="comuna_m2_bucket", sample_count=15, dispersion=25, price_m2=2_200_000),
        {"comuna": "nunoa", "m2": 75, "property_type": "apartment"},
    )

    assert not result.adjustment_applied
    assert result.adjustment_reason == "comuna_bucket_sample_count_below_threshold"


def test_surface_adjustment_applies_cautiously_to_high_dispersion_comuna_bucket() -> None:
    result = maybe_apply_surface_adjustment(
        150_000_000,
        _surface(level="comuna_m2_bucket", sample_count=30, dispersion=80, price_m2=2_200_000),
        {"comuna": "nunoa", "m2": 75, "property_type": "apartment"},
    )

    assert result.adjustment_applied
    assert result.adjustment_weight == 0.1
    assert "surface_adjustment_high_dispersion" in result.warnings


def test_surface_adjustment_does_not_apply_to_high_dispersion_microzone() -> None:
    result = maybe_apply_surface_adjustment(
        150_000_000,
        _surface(level="microzone_m2_bucket", sample_count=20, dispersion=60, price_m2=2_200_000),
        {"comuna": "nunoa", "m2": 75, "property_type": "apartment"},
    )

    assert not result.adjustment_applied
    assert result.adjustment_reason == "microzone_dispersion_too_high"


def test_surface_adjustment_applies_20_pct_only_for_strong_microzone_surface() -> None:
    result = maybe_apply_surface_adjustment(
        150_000_000,
        _surface(level="microzone_m2_bucket", sample_count=25, dispersion=25, price_m2=2_200_000),
        {"comuna": "nunoa", "m2": 75, "property_type": "apartment"},
        SurfaceAdjustmentConfig(historical_win_rate_by_level={"microzone_m2_bucket": 60.0}),
    )

    assert result.adjustment_applied
    assert result.adjustment_weight == 0.2
    assert result.adjusted_estimate == 153_000_000


def test_surface_adjustment_policy_allows_san_miguel_15_pct() -> None:
    result = maybe_apply_surface_adjustment(
        150_000_000,
        _surface(level="comuna_m2_bucket", sample_count=25, dispersion=40, price_m2=2_200_000),
        {"comuna": "san_miguel", "m2": 75, "property_type": "house"},
    )

    assert result.adjustment_applied
    assert result.adjustment_weight == 0.15
    assert "san_miguel_15pct" in result.adjustment_reason


def test_custom_segment_policy_can_override_by_property_type_and_level() -> None:
    result = maybe_apply_surface_adjustment(
        150_000_000,
        _surface(level="comuna_m2_bucket", sample_count=25, dispersion=40, price_m2=2_200_000),
        {"comuna": "nunoa", "m2": 75, "property_type": "apartment"},
        SurfaceAdjustmentConfig(
            segment_policies=(
                SegmentAdjustmentPolicy(
                    name="apartment_comuna_bucket_12pct",
                    property_type="apartment",
                    surface_level_used="comuna_m2_bucket",
                    adjustment_weight=0.12,
                    max_weight=0.12,
                ),
            )
        ),
    )

    assert result.adjustment_applied
    assert result.adjustment_weight == 0.12
    assert "apartment_comuna_bucket_12pct" in result.adjustment_reason


def test_surface_adjustment_does_not_change_property_type_matching() -> None:
    apartments = [
        make_listing(
            fingerprint=f"apt-adjust-{idx}",
            property_type="apartment",
            comuna="nunoa",
            m2=75,
            price_clp=150_000_000,
        )
        for idx in range(10)
    ]
    houses = [
        make_listing(
            fingerprint=f"house-adjust-{idx}",
            property_type="house",
            comuna="nunoa",
            m2=75,
            built_area_m2=75,
            land_area_m2=300,
            price_clp=900_000_000,
        )
        for idx in range(20)
    ]
    surface = lookup_price_surface(make_property(comuna="nunoa", property_type="apartment", m2=75), [*apartments, *houses])
    result = maybe_apply_surface_adjustment(
        180_000_000,
        surface,
        {"comuna": "nunoa", "m2": 75, "property_type": "apartment"},
    )

    assert surface.surface_price_m2 == 2_000_000
    assert not result.adjustment_applied
    assert result.adjustment_reason == "comuna_bucket_sample_count_below_threshold"
