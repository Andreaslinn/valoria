"""Adapter for the Radar playground view models."""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ui.redesign.radar_data import RADAR_DEMO_SOURCE, get_radar_demo_fixtures

RADAR_REAL_SOURCE = "real"
DATA_MODE_REAL = "real"
DATA_MODE_DEMO = "demo/lab"
RADAR_STATUS_READY = "ready"
RADAR_STATUS_EMPTY = "empty"
RADAR_STATUS_ERROR = "error"
RADAR_SCOPE_PROPERTY_TYPE = "Departamento"
RADAR_SCOPE_NOTE = "Radar beta: por ahora analiza solo departamentos. Casas quedan en pausa para esta beta."


@dataclass(frozen=True)
class RadarFilterCriteria:
    comuna: str = "Todas"
    price_range_uf: tuple[int, int] | None = None
    property_type: str = RADAR_SCOPE_PROPERTY_TYPE
    bedrooms_min: int | None = None
    min_score: int = 0
    sort_by: str = "score_desc"


@dataclass(frozen=True)
class RadarFiltersViewModel:
    comunas: tuple[str, ...]
    property_types: tuple[str, ...]
    bedroom_options: tuple[str, ...]
    sort_options: tuple[tuple[str, str], ...]
    price_min_uf: int
    price_max_uf: int
    default_price_range_uf: tuple[int, int]
    default_min_score: int
    source_state: str
    is_demo: bool
    property_type_enabled: bool = True
    bedrooms_enabled: bool = True


@dataclass(frozen=True)
class RadarOpportunityViewModel:
    id: str
    rank: int
    title: str
    comuna: str
    comuna_slug: str
    property_type: str
    property_type_slug: str
    bedrooms: int | None
    bathrooms: int | None
    parking: int | None
    m2: float
    published_price_uf: float
    published_price_m2_uf: float
    estimated_value_uf: float
    estimated_price_m2_uf: float
    discount_pct: float | None
    savings_uf: float
    score: int | None
    opportunity_score: int | None
    score_reason: str | None
    score_quality_flags: tuple[str, ...]
    confidence_pct: int
    comparable_count: int | None
    days_on_market: int
    liquidity: str
    risk: str
    status_label: str
    tone: str
    map_x_pct: float
    map_y_pct: float
    image_tone: str
    source_state: str
    is_demo: bool
    url: str | None = None
    lat: float | None = None
    lon: float | None = None
    geocode_precision: str | None = None
    price_basis_used: str | None = None
    price_data_quality: str | None = None
    price_uf_source: str | None = None
    uf_rate_used: float | None = None
    uf_rate_date: str | None = None
    uf_rate_fetched_at: str | None = None
    uf_rate_source: str | None = None
    uf_rate_cache_hit: bool | None = None
    uf_rate_stale: bool | None = None


@dataclass(frozen=True)
class RadarSummaryViewModel:
    active_opportunities: int
    new_this_week: int
    average_confidence_pct: int
    average_price_m2_uf: float
    filtered_count: int
    total_demo_opportunities: int
    label: str
    source_state: str
    is_demo: bool
    status: str = "available"
    sample_size: int = 0
    median_discount_pct: float | None = None
    median_price_uf: float | None = None
    median_price_m2_uf: float | None = None
    top_comunas: tuple[str, ...] = ()
    price_range_uf: tuple[float, float] | None = None
    predominant_bedrooms: int | None = None
    uf_rate_used: float | None = None
    detail: str | None = None


@dataclass(frozen=True)
class RadarTrendMetricViewModel:
    label: str
    value: str
    delta: str
    tone: str
    trend: tuple[int, ...]
    source_state: str
    is_demo: bool


@dataclass(frozen=True)
class RadarHotZoneViewModel:
    rank: int
    name: str
    score: int | None
    trend: tuple[int, ...]
    source_state: str
    is_demo: bool
    sample_size: int = 0
    median_discount_pct: float | None = None
    median_price_m2_uf: float | None = None
    median_confidence_pct: float | None = None
    status: str = "available"
    basis: str = "demo"


@dataclass(frozen=True)
class RadarRecentChangeViewModel:
    title: str
    detail: str
    time: str
    tone: str
    source_state: str
    is_demo: bool


@dataclass(frozen=True)
class RadarSavedSearchViewModel:
    name: str
    results: int
    state: str
    source_state: str
    is_demo: bool


@dataclass(frozen=True)
class RadarScoreFactorViewModel:
    label: str
    value: str
    caption: str
    tone: str
    state: str
    source_state: str
    is_demo: bool


@dataclass(frozen=True)
class RadarMapPinViewModel:
    rank: int
    label: str
    comuna: str
    score: int
    x_pct: float
    y_pct: float
    source_state: str
    is_demo: bool
    lat: float | None = None
    lon: float | None = None
    tooltip: str | None = None
    price_uf: float | None = None
    discount_pct: float | None = None
    geocode_precision: str | None = None


@dataclass(frozen=True)
class RadarMapHeatZoneViewModel:
    label: str
    x_pct: float
    y_pct: float
    intensity: int
    source_state: str
    is_demo: bool


@dataclass(frozen=True)
class RadarMapViewModel:
    title: str
    disclaimer: str
    pins: tuple[RadarMapPinViewModel, ...]
    heat_zones: tuple[RadarMapHeatZoneViewModel, ...]
    source_state: str
    is_demo: bool
    status: str = "available"
    empty_message: str | None = None
    reliable_points_count: int = 0
    excluded_weak_geocoding_count: int = 0
    coordinate_basis: str = "demo"


@dataclass(frozen=True)
class RadarViewModel:
    criteria: RadarFilterCriteria
    filters: RadarFiltersViewModel
    summary: RadarSummaryViewModel
    opportunities: tuple[RadarOpportunityViewModel, ...]
    market_summary: tuple[RadarTrendMetricViewModel, ...]
    hot_zones: tuple[RadarHotZoneViewModel, ...]
    recent_changes: tuple[RadarRecentChangeViewModel, ...]
    saved_searches: tuple[RadarSavedSearchViewModel, ...]
    score_breakdown: tuple[RadarScoreFactorViewModel, ...]
    map: RadarMapViewModel
    source_state: str
    is_demo: bool
    data_mode: str
    status: str
    error_message: str | None
    recent_changes_title: str
    recent_changes_badge: str


SORT_OPTIONS: tuple[tuple[str, str], ...] = (
    ("score_desc", "Mejor score"),
    ("discount_desc", "Mayor brecha"),
    ("price_asc", "Menor precio"),
    ("recent_asc", "Menor tiempo"),
)


def get_radar_view_model(
    criteria: RadarFilterCriteria | None = None,
    *,
    data_mode: str = DATA_MODE_DEMO,
    radar_opportunities: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    alerts: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    error_message: str | None = None,
) -> RadarViewModel:
    """Build the Radar playground model for real or demo/lab data."""
    if data_mode == DATA_MODE_REAL:
        return build_real_radar_view_model(
            criteria,
            radar_opportunities=radar_opportunities or (),
            alerts=alerts,
            error_message=error_message,
        )
    return build_radar_view_model(criteria)


def build_radar_view_model(
    criteria: RadarFilterCriteria | None = None,
    *,
    fixtures: dict[str, Any] | None = None,
) -> RadarViewModel:
    """Build a Radar playground view model from isolated demo fixtures."""
    data = deepcopy(fixtures) if fixtures is not None else get_radar_demo_fixtures()
    opportunities = tuple(_map_opportunity(item) for item in data.get("opportunities", ()))
    filters = _build_filters(data, opportunities)
    normalized_criteria = _normalize_criteria(criteria, filters)
    filtered = _filter_opportunities(opportunities, normalized_criteria)
    sorted_opportunities = tuple(_sort_opportunities(filtered, normalized_criteria.sort_by))
    summary = _map_summary(
        data.get("summary", {}),
        filtered_count=len(sorted_opportunities),
        total_demo_opportunities=len(opportunities),
    )
    return RadarViewModel(
        criteria=normalized_criteria,
        filters=filters,
        summary=summary,
        opportunities=sorted_opportunities,
        market_summary=tuple(_map_trend_metric(item) for item in data.get("market_summary", ())),
        hot_zones=tuple(_map_hot_zone(item) for item in data.get("hot_zones", ())),
        recent_changes=tuple(_map_recent_change(item) for item in data.get("recent_changes", ())),
        saved_searches=tuple(_map_saved_search(item) for item in data.get("saved_searches", ())),
        score_breakdown=tuple(_map_score_factor(item) for item in data.get("score_breakdown", ())),
        map=_map_map(data.get("map", {}), sorted_opportunities),
        source_state=_source_state(data),
        is_demo=_is_demo(data),
        data_mode=DATA_MODE_DEMO,
        status=RADAR_STATUS_EMPTY if not sorted_opportunities else RADAR_STATUS_READY,
        error_message=None,
        recent_changes_title="Cambios recientes",
        recent_changes_badge="Feed visual demo",
    )


def build_real_radar_view_model(
    criteria: RadarFilterCriteria | None = None,
    *,
    radar_opportunities: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    alerts: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    error_message: str | None = None,
) -> RadarViewModel:
    """Build a real Radar view model using existing backend responses."""
    raw_opportunities = list(radar_opportunities)
    opportunities = tuple(
        map_radar_opportunity_response(item, rank=index + 1)
        for index, item in enumerate(raw_opportunities)
    )
    filters = _build_real_filters(opportunities)
    normalized_criteria = _normalize_criteria(criteria, filters)
    filtered = _filter_opportunities(opportunities, normalized_criteria)
    sorted_opportunities = tuple(_rerank(_sort_opportunities(filtered, normalized_criteria.sort_by)))
    status = _status_for_real(error_message, raw_opportunities)
    return RadarViewModel(
        criteria=normalized_criteria,
        filters=filters,
        summary=_real_summary(
            sorted_opportunities,
            total_real_opportunities=len(opportunities),
            status=status,
        ),
        opportunities=sorted_opportunities if status != RADAR_STATUS_ERROR else (),
        market_summary=_real_market_summary_metrics(sorted_opportunities, status=status),
        hot_zones=_real_hot_zones(sorted_opportunities, status=status),
        recent_changes=tuple(_map_alert_response(item) for item in (alerts or ())),
        saved_searches=(),
        score_breakdown=_real_score_breakdown(sorted_opportunities, status=status),
        map=_real_map(sorted_opportunities, status=status),
        source_state=RADAR_REAL_SOURCE,
        is_demo=False,
        data_mode=DATA_MODE_REAL,
        status=status,
        error_message=error_message,
        recent_changes_title="Alertas de tus guardados",
        recent_changes_badge="Backend real",
    )


def map_radar_opportunity_response(
    item: dict[str, Any],
    *,
    rank: int,
) -> RadarOpportunityViewModel:
    """Map the existing /radar/opportunities response into the playground shape."""
    price_uf = _safe_float(item.get("price_uf"))
    m2 = _safe_float(item.get("m2"))
    estimated_value_uf = _safe_float(item.get("estimated_value_uf"))
    estimated_price_uf = _safe_float(item.get("estimated_price_uf"))
    estimated = estimated_value_uf or estimated_price_uf
    discount_pct = _safe_float(item.get("discount_pct"))
    score = _score_to_display(_first_present(item, "opportunity_score", "score"))
    confidence_pct = _confidence_pct(item)
    comparable_count = _safe_int(_first_present(item, "comparables_used", "comparable_count"))
    return RadarOpportunityViewModel(
        id=str(item.get("listing_id") or f"real-radar-{rank}"),
        rank=rank,
        title=str(item.get("title") or "Oportunidad real"),
        comuna=str(item.get("comuna") or "Sin comuna"),
        comuna_slug=_norm(item.get("comuna")),
        property_type=_property_type_label(item.get("property_type")),
        property_type_slug=str(item.get("property_type_slug") or "departamento"),
        bedrooms=_safe_int(_first_present(item, "bedrooms", "dormitorios")),
        bathrooms=_safe_int(_first_present(item, "bathrooms", "banos")),
        parking=_safe_int(_first_present(item, "parking", "estacionamientos", "parking_spaces")),
        m2=m2 or 0,
        published_price_uf=price_uf or 0,
        published_price_m2_uf=_price_m2(price_uf, m2),
        estimated_value_uf=estimated or 0,
        estimated_price_m2_uf=_price_m2(estimated, m2),
        discount_pct=discount_pct,
        savings_uf=max((estimated or 0) - (price_uf or 0), 0),
        score=score,
        opportunity_score=score,
        score_reason=_score_reason(item),
        score_quality_flags=tuple(str(flag) for flag in item.get("score_quality_flags", ()) if flag),
        confidence_pct=confidence_pct,
        comparable_count=comparable_count,
        days_on_market=0,
        liquidity="Coming soon",
        risk=str(item.get("radar_verdict") or "beta"),
        status_label="Real",
        tone=_tone_for_real_opportunity(discount_pct, score),
        map_x_pct=50,
        map_y_pct=50,
        image_tone=_image_tone(rank),
        source_state=RADAR_REAL_SOURCE,
        is_demo=False,
        url=str(item.get("url")) if item.get("url") else None,
        lat=_safe_float(item.get("lat")),
        lon=_safe_float(item.get("lon")),
        geocode_precision=str(item.get("geocode_precision")) if item.get("geocode_precision") else None,
        price_basis_used=str(item.get("price_basis_used")) if item.get("price_basis_used") else None,
        price_data_quality=str(item.get("price_data_quality")) if item.get("price_data_quality") else None,
        price_uf_source=str(item.get("price_uf_source")) if item.get("price_uf_source") else None,
        uf_rate_used=_safe_float(item.get("uf_rate_used")),
        uf_rate_date=str(item.get("uf_rate_date")) if item.get("uf_rate_date") else None,
        uf_rate_fetched_at=str(item.get("uf_rate_fetched_at")) if item.get("uf_rate_fetched_at") else None,
        uf_rate_source=str(item.get("uf_rate_source")) if item.get("uf_rate_source") else None,
        uf_rate_cache_hit=bool(item.get("uf_rate_cache_hit")) if item.get("uf_rate_cache_hit") is not None else None,
        uf_rate_stale=bool(item.get("uf_rate_stale")) if item.get("uf_rate_stale") is not None else None,
    )


def _build_filters(
    data: dict[str, Any],
    opportunities: tuple[RadarOpportunityViewModel, ...],
) -> RadarFiltersViewModel:
    filter_data = data.get("filters", {})
    comunas = tuple(sorted({item.comuna for item in opportunities}))
    return RadarFiltersViewModel(
        comunas=("Todas", *comunas),
        property_types=(RADAR_SCOPE_PROPERTY_TYPE,),
        bedroom_options=("Todos", "1+", "2+", "3+", "4+"),
        sort_options=SORT_OPTIONS,
        price_min_uf=int(filter_data.get("price_min_uf") or 0),
        price_max_uf=int(filter_data.get("price_max_uf") or 25000),
        default_price_range_uf=tuple(filter_data.get("default_price_range_uf") or (4000, 25000)),  # type: ignore[arg-type]
        default_min_score=int(filter_data.get("default_min_score") or 60),
        source_state=_source_state(filter_data),
        is_demo=_is_demo(filter_data),
        property_type_enabled=False,
    )


def _build_real_filters(
    opportunities: tuple[RadarOpportunityViewModel, ...],
) -> RadarFiltersViewModel:
    prices = [int(item.published_price_uf) for item in opportunities if item.published_price_uf > 0]
    price_min = min(prices) if prices else 0
    price_max = max(prices) if prices else 25000
    if price_min == price_max:
        price_min = max(price_min - 1000, 0)
        price_max += 1000
    comunas = tuple(sorted({item.comuna for item in opportunities if item.comuna}))
    return RadarFiltersViewModel(
        comunas=("Todas", *comunas),
        property_types=(RADAR_SCOPE_PROPERTY_TYPE,),
        bedroom_options=("Todos", "1+", "2+", "3+", "4+"),
        sort_options=tuple(option for option in SORT_OPTIONS if option[0] != "recent_asc"),
        price_min_uf=price_min,
        price_max_uf=price_max,
        default_price_range_uf=(price_min, price_max),
        default_min_score=0,
        source_state=RADAR_REAL_SOURCE,
        is_demo=False,
        property_type_enabled=False,
    )


def _normalize_criteria(
    criteria: RadarFilterCriteria | None,
    filters: RadarFiltersViewModel,
) -> RadarFilterCriteria:
    current = criteria or RadarFilterCriteria(
        price_range_uf=filters.default_price_range_uf,
        min_score=filters.default_min_score,
    )
    comuna = current.comuna if current.comuna in filters.comunas else "Todas"
    property_type = (
        current.property_type
        if current.property_type in filters.property_types
        else RADAR_SCOPE_PROPERTY_TYPE
    )
    price_range = current.price_range_uf or filters.default_price_range_uf
    low = max(filters.price_min_uf, int(min(price_range)))
    high = min(filters.price_max_uf, int(max(price_range)))
    sort_keys = {key for key, _label in filters.sort_options}
    sort_by = current.sort_by if current.sort_by in sort_keys else "score_desc"
    return RadarFilterCriteria(
        comuna=comuna,
        price_range_uf=(low, high),
        property_type=property_type,
        bedrooms_min=current.bedrooms_min,
        min_score=max(0, min(100, int(current.min_score))),
        sort_by=sort_by,
    )


def _filter_opportunities(
    opportunities: tuple[RadarOpportunityViewModel, ...],
    criteria: RadarFilterCriteria,
) -> list[RadarOpportunityViewModel]:
    results: list[RadarOpportunityViewModel] = []
    low, high = criteria.price_range_uf or (0, 999999)
    for item in opportunities:
        if criteria.comuna != "Todas" and _norm(item.comuna) != _norm(criteria.comuna):
            continue
        if criteria.property_type != "Todos" and _norm(item.property_type) != _norm(criteria.property_type):
            continue
        if criteria.bedrooms_min is not None and (
            item.bedrooms is None or item.bedrooms < criteria.bedrooms_min
        ):
            continue
        if not (low <= item.published_price_uf <= high):
            continue
        if _score_value(item.score) < criteria.min_score:
            continue
        results.append(item)
    return results


def _sort_opportunities(
    opportunities: list[RadarOpportunityViewModel],
    sort_by: str,
) -> list[RadarOpportunityViewModel]:
    if sort_by == "discount_desc":
        return sorted(opportunities, key=lambda item: (_number_value(item.discount_pct), _score_value(item.score)), reverse=True)
    if sort_by == "price_asc":
        return sorted(opportunities, key=lambda item: (item.published_price_uf, -_score_value(item.score)))
    if sort_by == "recent_asc":
        return sorted(opportunities, key=lambda item: (item.days_on_market, -_score_value(item.score)))
    return sorted(opportunities, key=lambda item: (_score_value(item.score), _number_value(item.discount_pct)), reverse=True)


def _map_opportunity(item: dict[str, Any]) -> RadarOpportunityViewModel:
    return RadarOpportunityViewModel(
        id=str(item.get("id") or ""),
        rank=int(item.get("rank") or 0),
        title=str(item.get("title") or "Oportunidad demo"),
        comuna=str(item.get("comuna") or ""),
        comuna_slug=str(item.get("comuna_slug") or _norm(item.get("comuna"))),
        property_type=str(item.get("property_type") or ""),
        property_type_slug=str(item.get("property_type_slug") or _norm(item.get("property_type"))),
        bedrooms=_safe_int(item.get("bedrooms")),
        bathrooms=_safe_int(item.get("bathrooms")),
        parking=_safe_int(item.get("parking")),
        m2=float(item.get("m2") or 0),
        published_price_uf=float(item.get("published_price_uf") or 0),
        published_price_m2_uf=float(item.get("published_price_m2_uf") or 0),
        estimated_value_uf=float(item.get("estimated_value_uf") or 0),
        estimated_price_m2_uf=float(item.get("estimated_price_m2_uf") or 0),
        discount_pct=float(item.get("discount_pct") or 0),
        savings_uf=float(item.get("savings_uf") or 0),
        score=int(item.get("score") or 0),
        opportunity_score=int(item.get("score") or 0),
        score_reason=str(item.get("score_reason") or "Score demo/lab."),
        score_quality_flags=tuple(str(flag) for flag in item.get("score_quality_flags", ()) if flag),
        confidence_pct=int(item.get("confidence_pct") or 0),
        comparable_count=_safe_int(item.get("comparable_count")),
        days_on_market=int(item.get("days_on_market") or 0),
        liquidity=str(item.get("liquidity") or "Demo"),
        risk=str(item.get("risk") or "Demo"),
        status_label=str(item.get("status_label") or RADAR_DEMO_SOURCE),
        tone=str(item.get("tone") or "neutral"),
        map_x_pct=float(item.get("map_x_pct") or 50),
        map_y_pct=float(item.get("map_y_pct") or 50),
        image_tone=str(item.get("image_tone") or "blue"),
        source_state=_source_state(item),
        is_demo=_is_demo(item),
        url=str(item.get("url")) if item.get("url") else None,
        lat=_safe_float(item.get("lat")),
        lon=_safe_float(item.get("lon")),
        geocode_precision=str(item.get("geocode_precision")) if item.get("geocode_precision") else None,
    )


def _map_summary(
    item: dict[str, Any],
    *,
    filtered_count: int,
    total_demo_opportunities: int,
) -> RadarSummaryViewModel:
    return RadarSummaryViewModel(
        active_opportunities=int(item.get("active_opportunities") or filtered_count),
        new_this_week=int(item.get("new_this_week") or 0),
        average_confidence_pct=int(item.get("average_confidence_pct") or 0),
        average_price_m2_uf=float(item.get("average_price_m2_uf") or 0),
        filtered_count=filtered_count,
        total_demo_opportunities=total_demo_opportunities,
        label=str(item.get("label") or "Radar demo"),
        source_state=_source_state(item),
        is_demo=_is_demo(item),
    )


def _real_summary(
    opportunities: tuple[RadarOpportunityViewModel, ...],
    *,
    total_real_opportunities: int,
    status: str,
) -> RadarSummaryViewModel:
    avg_confidence = _average_int(item.confidence_pct for item in opportunities)
    avg_price_m2 = _average_float(
        item.published_price_m2_uf for item in opportunities if item.published_price_m2_uf > 0
    )
    prices = [item.published_price_uf for item in opportunities if item.published_price_uf > 0]
    top_comunas = tuple(name for name, _count in Counter(item.comuna for item in opportunities if item.comuna).most_common(3))
    bedrooms = [item.bedrooms for item in opportunities if item.bedrooms is not None]
    sample_size = len(opportunities) if status != RADAR_STATUS_ERROR else 0
    return RadarSummaryViewModel(
        active_opportunities=total_real_opportunities if status != RADAR_STATUS_ERROR else 0,
        new_this_week=0,
        average_confidence_pct=avg_confidence,
        average_price_m2_uf=avg_price_m2,
        filtered_count=sample_size,
        total_demo_opportunities=total_real_opportunities,
        label="Radar backend real",
        source_state=RADAR_REAL_SOURCE,
        is_demo=False,
        status="available" if sample_size else "empty",
        sample_size=sample_size,
        median_discount_pct=_median(item.discount_pct for item in opportunities),
        median_price_uf=_median(prices),
        median_price_m2_uf=_median(item.published_price_m2_uf for item in opportunities if item.published_price_m2_uf > 0),
        top_comunas=top_comunas,
        price_range_uf=(min(prices), max(prices)) if prices else None,
        predominant_bedrooms=Counter(bedrooms).most_common(1)[0][0] if bedrooms else None,
        uf_rate_used=_first_non_null(item.uf_rate_used for item in opportunities),
        detail=f"Resumen basado en {sample_size} resultados de Radar." if sample_size else "Datos insuficientes para resumen de mercado.",
    )


def _real_market_summary_metrics(
    opportunities: tuple[RadarOpportunityViewModel, ...],
    *,
    status: str,
) -> tuple[RadarTrendMetricViewModel, ...]:
    if status == RADAR_STATUS_ERROR or not opportunities:
        return ()
    summary = _real_summary(opportunities, total_real_opportunities=len(opportunities), status=status)
    return (
        RadarTrendMetricViewModel(
            label="Muestra Radar",
            value=str(summary.sample_size),
            delta="resultados reales",
            tone="positive" if summary.sample_size >= 3 else "warning",
            trend=(),
            source_state=RADAR_REAL_SOURCE,
            is_demo=False,
        ),
        RadarTrendMetricViewModel(
            label="Precio mediano",
            value=_format_uf_compact(summary.median_price_uf),
            delta="publicado",
            tone="neutral",
            trend=(),
            source_state=RADAR_REAL_SOURCE,
            is_demo=False,
        ),
        RadarTrendMetricViewModel(
            label="UF/m2 mediana",
            value=_format_uf_m2_compact(summary.median_price_m2_uf),
            delta="publicada",
            tone="neutral",
            trend=(),
            source_state=RADAR_REAL_SOURCE,
            is_demo=False,
        ),
        RadarTrendMetricViewModel(
            label="Descuento mediano",
            value=_format_pct_compact(summary.median_discount_pct),
            delta="estimado por Radar",
            tone="positive" if _number_value(summary.median_discount_pct) >= 10 else "warning",
            trend=(),
            source_state=RADAR_REAL_SOURCE,
            is_demo=False,
        ),
    )


def _real_hot_zones(
    opportunities: tuple[RadarOpportunityViewModel, ...],
    *,
    status: str,
) -> tuple[RadarHotZoneViewModel, ...]:
    if status == RADAR_STATUS_ERROR or not opportunities:
        return ()
    grouped: dict[str, list[RadarOpportunityViewModel]] = defaultdict(list)
    for item in opportunities:
        if item.comuna:
            grouped[item.comuna].append(item)
    zones: list[RadarHotZoneViewModel] = []
    for name, items in grouped.items():
        sample_size = len(items)
        median_score = _median(_score_value(item.score) for item in items if item.score is not None)
        median_discount = _median(item.discount_pct for item in items)
        status_label = "sample_ok" if sample_size >= 3 else "sample_low"
        zones.append(
            RadarHotZoneViewModel(
                rank=0,
                name=name,
                score=round(median_score) if median_score is not None else None,
                trend=(),
                source_state=RADAR_REAL_SOURCE,
                is_demo=False,
                sample_size=sample_size,
                median_discount_pct=median_discount,
                median_price_m2_uf=_median(item.published_price_m2_uf for item in items if item.published_price_m2_uf > 0),
                median_confidence_pct=_median(item.confidence_pct for item in items if item.confidence_pct > 0),
                status=status_label,
                basis="por comuna",
            )
        )
    zones.sort(
        key=lambda zone: (
            zone.sample_size >= 3,
            _number_value(zone.median_discount_pct),
            zone.sample_size,
            _score_value(zone.score),
        ),
        reverse=True,
    )
    return tuple(
        RadarHotZoneViewModel(
            rank=index,
            name=zone.name,
            score=zone.score,
            trend=zone.trend,
            source_state=zone.source_state,
            is_demo=zone.is_demo,
            sample_size=zone.sample_size,
            median_discount_pct=zone.median_discount_pct,
            median_price_m2_uf=zone.median_price_m2_uf,
            median_confidence_pct=zone.median_confidence_pct,
            status=zone.status,
            basis=zone.basis,
        )
        for index, zone in enumerate(zones[:5], start=1)
    )


def _real_score_breakdown(
    opportunities: tuple[RadarOpportunityViewModel, ...],
    *,
    status: str,
) -> tuple[RadarScoreFactorViewModel, ...]:
    if status == RADAR_STATUS_ERROR or not opportunities:
        return (
            RadarScoreFactorViewModel(
                label="Score Radar",
                value="N/D",
                caption="Score basado en descuento estimado, confianza y senales disponibles de Radar.",
                tone="warning",
                state="sin datos",
                source_state=RADAR_REAL_SOURCE,
                is_demo=False,
            ),
        )
    scores = [item.score for item in opportunities if item.score is not None]
    median_score = _median(scores)
    return (
        RadarScoreFactorViewModel(
            label="Score Radar",
            value=_format_score(median_score),
            caption="Score basado en descuento estimado, confianza y senales disponibles de Radar.",
            tone="positive" if _number_value(median_score) >= 60 else "warning",
            state="real",
            source_state=RADAR_REAL_SOURCE,
            is_demo=False,
        ),
        RadarScoreFactorViewModel(
            label="Descuento estimado",
            value=_format_pct_compact(_median(item.discount_pct for item in opportunities)),
            caption="Mediana de brecha frente al valor estimado.",
            tone="positive",
            state="real",
            source_state=RADAR_REAL_SOURCE,
            is_demo=False,
        ),
        RadarScoreFactorViewModel(
            label="Confianza",
            value=_format_pct_compact(_median(item.confidence_pct for item in opportunities if item.confidence_pct > 0)),
            caption="Mediana de confianza reportada por Radar.",
            tone="neutral",
            state="real",
            source_state=RADAR_REAL_SOURCE,
            is_demo=False,
        ),
        RadarScoreFactorViewModel(
            label="Comparables",
            value=_format_count(_median(item.comparable_count for item in opportunities if item.comparable_count is not None)),
            caption="Mediana de comparables usados.",
            tone="neutral",
            state="real",
            source_state=RADAR_REAL_SOURCE,
            is_demo=False,
        ),
    )


def _real_map(
    opportunities: tuple[RadarOpportunityViewModel, ...],
    *,
    status: str,
) -> RadarMapViewModel:
    if status == RADAR_STATUS_ERROR:
        return _empty_real_map("Mapa experimental no disponible: Radar no respondio.")
    candidates = [item for item in opportunities if _norm(item.property_type) == _norm(RADAR_SCOPE_PROPERTY_TYPE)]
    reliable = [item for item in candidates if _has_reliable_coordinates(item)]
    excluded = len([item for item in candidates if item.lat is not None or item.lon is not None]) - len(reliable)
    if not reliable:
        return _empty_real_map(
            "Mapa experimental no disponible: faltan coordenadas confiables.",
            excluded_weak_geocoding_count=max(excluded, 0),
        )
    lat_values = [item.lat for item in reliable if item.lat is not None]
    lon_values = [item.lon for item in reliable if item.lon is not None]
    pins = tuple(
        RadarMapPinViewModel(
            rank=index,
            label=item.title,
            comuna=item.comuna,
            score=_score_value(item.score),
            x_pct=_scale_between(item.lon, min(lon_values), max(lon_values)),
            y_pct=100 - _scale_between(item.lat, min(lat_values), max(lat_values)),
            source_state=RADAR_REAL_SOURCE,
            is_demo=False,
            lat=item.lat,
            lon=item.lon,
            tooltip=_map_tooltip(item),
            price_uf=item.published_price_uf,
            discount_pct=item.discount_pct,
            geocode_precision=item.geocode_precision,
        )
        for index, item in enumerate(reliable[:20], start=1)
    )
    return RadarMapViewModel(
        title="Mapa experimental",
        disclaimer="Mapa experimental basado en coordenadas disponibles.",
        pins=pins,
        heat_zones=(),
        source_state=RADAR_REAL_SOURCE,
        is_demo=False,
        status="available",
        reliable_points_count=len(pins),
        excluded_weak_geocoding_count=max(excluded, 0),
        coordinate_basis="coordenadas reales",
    )


def _empty_real_map(message: str, *, excluded_weak_geocoding_count: int = 0) -> RadarMapViewModel:
    return RadarMapViewModel(
        title="Mapa experimental",
        disclaimer=message,
        pins=(),
        heat_zones=(),
        source_state=RADAR_REAL_SOURCE,
        is_demo=False,
        status="empty",
        empty_message=message,
        excluded_weak_geocoding_count=excluded_weak_geocoding_count,
        coordinate_basis="coordenadas reales",
    )


def _map_trend_metric(item: dict[str, Any]) -> RadarTrendMetricViewModel:
    return RadarTrendMetricViewModel(
        label=str(item.get("label") or ""),
        value=str(item.get("value") or ""),
        delta=str(item.get("delta") or ""),
        tone=str(item.get("tone") or "neutral"),
        trend=tuple(int(value) for value in item.get("trend", ())),
        source_state=_source_state(item),
        is_demo=_is_demo(item),
    )


def _map_hot_zone(item: dict[str, Any]) -> RadarHotZoneViewModel:
    return RadarHotZoneViewModel(
        rank=int(item.get("rank") or 0),
        name=str(item.get("name") or ""),
        score=int(item.get("score") or 0),
        trend=tuple(int(value) for value in item.get("trend", ())),
        source_state=_source_state(item),
        is_demo=_is_demo(item),
    )


def _map_recent_change(item: dict[str, Any]) -> RadarRecentChangeViewModel:
    return RadarRecentChangeViewModel(
        title=str(item.get("title") or ""),
        detail=str(item.get("detail") or ""),
        time=str(item.get("time") or ""),
        tone=str(item.get("tone") or "neutral"),
        source_state=_source_state(item),
        is_demo=_is_demo(item),
    )


def _map_alert_response(item: dict[str, Any]) -> RadarRecentChangeViewModel:
    return RadarRecentChangeViewModel(
        title=str(item.get("title") or _alert_title(item.get("alert_type"))),
        detail=str(item.get("message") or item.get("comuna") or "Alerta real de propiedad guardada"),
        time=_format_alert_time(item.get("created_at")),
        tone=_tone_for_alert(item.get("alert_type")),
        source_state=RADAR_REAL_SOURCE,
        is_demo=False,
    )


def _map_saved_search(item: dict[str, Any]) -> RadarSavedSearchViewModel:
    return RadarSavedSearchViewModel(
        name=str(item.get("name") or ""),
        results=int(item.get("results") or 0),
        state=str(item.get("state") or "coming_soon"),
        source_state=_source_state(item),
        is_demo=_is_demo(item),
    )


def _map_score_factor(item: dict[str, Any]) -> RadarScoreFactorViewModel:
    return RadarScoreFactorViewModel(
        label=str(item.get("label") or ""),
        value=str(item.get("value") or ""),
        caption=str(item.get("caption") or ""),
        tone=str(item.get("tone") or "neutral"),
        state=str(item.get("state") or "demo"),
        source_state=_source_state(item),
        is_demo=_is_demo(item),
    )


def _map_map(
    item: dict[str, Any],
    opportunities: tuple[RadarOpportunityViewModel, ...],
) -> RadarMapViewModel:
    return RadarMapViewModel(
        title=str(item.get("title") or "Mapa experimental"),
        disclaimer=str(item.get("disclaimer") or "Vista simulada; pendiente geocodificacion real."),
        pins=tuple(
            RadarMapPinViewModel(
                rank=opportunity.rank,
                label=opportunity.title,
                comuna=opportunity.comuna,
                score=_score_value(opportunity.score),
                x_pct=opportunity.map_x_pct,
                y_pct=opportunity.map_y_pct,
                source_state=opportunity.source_state,
                is_demo=opportunity.is_demo,
                tooltip=opportunity.title,
            )
            for opportunity in opportunities
        ),
        heat_zones=tuple(_map_heat_zone(zone) for zone in item.get("heat_zones", ())),
        source_state=_source_state(item),
        is_demo=_is_demo(item),
    )


def _map_demo_only_map(
    item: dict[str, Any],
    demo_opportunities: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> RadarMapViewModel:
    demo_view_models = tuple(_map_opportunity(row) for row in demo_opportunities)
    return _map_map(item, demo_view_models)


def _map_heat_zone(item: dict[str, Any]) -> RadarMapHeatZoneViewModel:
    return RadarMapHeatZoneViewModel(
        label=str(item.get("label") or ""),
        x_pct=float(item.get("x_pct") or 50),
        y_pct=float(item.get("y_pct") or 50),
        intensity=int(item.get("intensity") or 0),
        source_state=_source_state(item),
        is_demo=_is_demo(item),
    )


def _source_state(item: dict[str, Any]) -> str:
    return str(item.get("source_state") or RADAR_DEMO_SOURCE)


def _is_demo(item: dict[str, Any]) -> bool:
    return bool(item.get("is_demo", True))


def _rerank(opportunities: list[RadarOpportunityViewModel]) -> tuple[RadarOpportunityViewModel, ...]:
    return tuple(
        RadarOpportunityViewModel(
            id=item.id,
            rank=index,
            title=item.title,
            comuna=item.comuna,
            comuna_slug=item.comuna_slug,
            property_type=item.property_type,
            property_type_slug=item.property_type_slug,
            bedrooms=item.bedrooms,
            bathrooms=item.bathrooms,
            parking=item.parking,
            m2=item.m2,
            published_price_uf=item.published_price_uf,
            published_price_m2_uf=item.published_price_m2_uf,
            estimated_value_uf=item.estimated_value_uf,
            estimated_price_m2_uf=item.estimated_price_m2_uf,
            discount_pct=item.discount_pct,
            savings_uf=item.savings_uf,
            score=item.score,
            opportunity_score=item.opportunity_score,
            score_reason=item.score_reason,
            score_quality_flags=item.score_quality_flags,
            confidence_pct=item.confidence_pct,
            comparable_count=item.comparable_count,
            days_on_market=item.days_on_market,
            liquidity=item.liquidity,
            risk=item.risk,
            status_label=item.status_label,
            tone=item.tone,
            map_x_pct=item.map_x_pct,
            map_y_pct=item.map_y_pct,
            image_tone=item.image_tone,
            source_state=item.source_state,
            is_demo=item.is_demo,
            url=item.url,
            lat=item.lat,
            lon=item.lon,
            geocode_precision=item.geocode_precision,
            price_basis_used=item.price_basis_used,
            price_data_quality=item.price_data_quality,
            price_uf_source=item.price_uf_source,
            uf_rate_used=item.uf_rate_used,
            uf_rate_date=item.uf_rate_date,
            uf_rate_fetched_at=item.uf_rate_fetched_at,
            uf_rate_source=item.uf_rate_source,
            uf_rate_cache_hit=item.uf_rate_cache_hit,
            uf_rate_stale=item.uf_rate_stale,
        )
        for index, item in enumerate(opportunities, start=1)
    )


def _status_for_real(error_message: str | None, raw_opportunities: list[dict[str, Any]]) -> str:
    if error_message:
        return RADAR_STATUS_ERROR
    if not raw_opportunities:
        return RADAR_STATUS_EMPTY
    return RADAR_STATUS_READY


def _score_to_display(value: Any) -> int | None:
    number = _safe_float(value)
    if number is None:
        return None
    if 0 <= number <= 1:
        return round(number * 100)
    return round(number)


def _confidence_pct(item: dict[str, Any]) -> int:
    score = _safe_float(item.get("confidence_score"))
    if score is not None:
        return round(score * 100 if score <= 1 else score)
    label = str(item.get("confidence_label") or item.get("confidence") or "").lower()
    if label in {"high", "alta"}:
        return 85
    if label in {"medium", "media"}:
        return 65
    if label in {"low", "baja"}:
        return 40
    return 0


def _price_m2(price_uf: float | None, m2: float | None) -> float:
    if price_uf is None or m2 is None or m2 <= 0:
        return 0
    return round(price_uf / m2, 1)


def _tone_for_real_opportunity(discount_pct: float | None, score: int | None) -> str:
    score_value = _score_value(score)
    if score_value >= 60 or (discount_pct is not None and discount_pct >= 10):
        return "positive"
    if score_value >= 30 or (discount_pct is not None and discount_pct >= 5):
        return "warning"
    return "neutral"


def _image_tone(rank: int) -> str:
    tones = ("cyan", "blue", "purple", "teal", "amber", "violet")
    return tones[(rank - 1) % len(tones)]


def _alert_title(value: Any) -> str:
    if str(value or "") == "price_drop":
        return "Baja de precio"
    return "Alerta de propiedad guardada"


def _tone_for_alert(value: Any) -> str:
    if str(value or "") == "price_drop":
        return "positive"
    return "neutral"


def _format_alert_time(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d/%m %H:%M")
    text = str(value or "")
    if not text:
        return "Reciente"
    try:
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).strftime("%d/%m %H:%M")
    except ValueError:
        return text


def _average_int(values: Any) -> int:
    clean = [int(value) for value in values if value is not None]
    if not clean:
        return 0
    return round(sum(clean) / len(clean))


def _average_float(values: Any) -> float:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return 0.0
    return round(sum(clean) / len(clean), 1)


def _median(values: Any) -> float | None:
    clean = sorted(float(value) for value in values if value is not None)
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2:
        return round(clean[mid], 2)
    return round((clean[mid - 1] + clean[mid]) / 2, 2)


def _first_non_null(values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _score_value(value: int | float | None) -> int:
    return int(value) if value is not None else 0


def _number_value(value: int | float | None) -> float:
    return float(value) if value is not None else 0.0


def _format_score(value: int | float | None) -> str:
    if value is None:
        return "N/D"
    return str(round(float(value)))


def _format_count(value: int | float | None) -> str:
    if value is None:
        return "N/D"
    return str(round(float(value)))


def _format_uf_compact(value: float | None) -> str:
    if value is None:
        return "N/D"
    return f"UF {value:,.0f}".replace(",", ".")


def _format_uf_m2_compact(value: float | None) -> str:
    if value is None:
        return "N/D"
    return f"UF {value:.1f}/m2".replace(".", ",")


def _format_pct_compact(value: float | None) -> str:
    if value is None:
        return "N/D"
    return f"{value:.1f}%".replace(".", ",")


def _score_reason(item: dict[str, Any]) -> str:
    explicit = str(item.get("score_reason") or "").strip()
    if explicit:
        return explicit
    return "Score basado en descuento estimado, confianza y senales disponibles de Radar."


def _has_reliable_coordinates(item: RadarOpportunityViewModel) -> bool:
    if item.lat is None or item.lon is None:
        return False
    precision = _norm(item.geocode_precision)
    if precision in {"", "unknown", "comuna", "comuna_centroid", "title_inferred", "title_inferred_low"}:
        return False
    return -90 <= item.lat <= 90 and -180 <= item.lon <= 180


def _scale_between(value: float | None, low: float, high: float) -> float:
    if value is None or low == high:
        return 50.0
    return max(5.0, min(95.0, ((value - low) / (high - low)) * 90.0 + 5.0))


def _map_tooltip(item: RadarOpportunityViewModel) -> str:
    return " | ".join(
        part
        for part in [
            item.title,
            item.comuna,
            _format_uf_compact(item.published_price_uf if item.published_price_uf > 0 else None),
            f"descuento {_format_pct_compact(item.discount_pct)}",
            f"score {_format_score(item.score)}",
        ]
        if part
    )


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_present(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None


def _property_type_label(value: Any) -> str:
    normalized = _norm(value)
    if normalized in {"apartment", "departamento", "depto"}:
        return RADAR_SCOPE_PROPERTY_TYPE
    if normalized in {"house", "casa"}:
        return "Casa"
    return RADAR_SCOPE_PROPERTY_TYPE


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")
