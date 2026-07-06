"""Read-only v0 market intelligence summaries for the dashboard."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.entities.listing import Listing
from core.value_objects.price import Price
from domain.radar.freshness import RadarFreshnessConfig, is_fresh_for_radar
from infrastructure.db.models import ListingORM, PriceHistoryORM

BETA_PROPERTY_TYPE = "apartment"
GOOD_GEOCODE_PRECISIONS = frozenset({"address", "street"})
RELIABLE_PRICE_UF_CONFIDENCE = frozenset({"high", "medium", "derived", "explicit"})
MICROZONE_KEYS = (
    "microzone_id",
    "microzone",
    "microzona",
    "sector",
    "neighborhood",
    "barrio",
)


@dataclass(frozen=True)
class ListingSignal:
    id: int | None
    comuna: str
    status: str
    price_uf: float | None
    price_uf_confidence: str | None
    url: str | None
    usable_area_m2: float | None
    built_area_m2: float | None
    m2: float | None
    geocode_precision: str | None
    raw_metadata: dict[str, Any]
    scraped_at: datetime
    last_seen_at: datetime | None
    last_refresh_attempted_at: datetime | None
    last_refresh_status: str | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class MarketDataset:
    now: datetime
    scoped: list[ListingSignal]
    active: list[ListingSignal]
    fresh: list[ListingSignal]
    stale_count: int
    missing_url_count: int
    removed_or_inactive_count: int
    new_listings_24h: int
    new_listings_7d: int
    removed_7d: int
    price_changes_30d: int


async def build_market_briefing(
    session: AsyncSession,
    *,
    max_staleness_days: int = 7,
) -> dict[str, Any]:
    dataset = await _load_market_dataset(session, max_staleness_days=max_staleness_days)
    active_count = len(dataset.active)
    fresh_count = len(dataset.fresh)

    if active_count == 0:
        return market_briefing_placeholder(status="empty")

    valoria_index = _build_valoria_index(dataset)
    status = _market_status(active_count)
    return {
        "status": status,
        "available": True,
        "market": "Santiago, Chile",
        "headline": "Valoria monitorea el mercado activo",
        "summary": (
            "Resumen basado en publicaciones activas, frescura y actividad reciente."
        ),
        "indicators": [
            {
                "key": "active_supply",
                "label": "Oferta en mercado",
                "status": status,
                "value": active_count,
                "delta_pct": None,
                "unit": "publicaciones",
                "description": "Departamentos activos en el scope beta.",
            },
            {
                "key": "fresh_listings",
                "label": "Publicaciones vigentes",
                "status": status,
                "value": fresh_count,
                "delta_pct": None,
                "unit": "confirmadas",
                "description": "Publicaciones activas confirmadas recientemente.",
            },
            {
                "key": "new_listings_7d",
                "label": "Nuevas publicaciones",
                "status": status,
                "value": dataset.new_listings_7d,
                "delta_pct": None,
                "unit": "7 dias",
                "description": "Publicaciones nuevas detectadas en los ultimos 7 dias.",
            },
        ],
        "insight": {
            "status": status,
            "text": (
                f"Hay {fresh_count} publicaciones vigentes dentro del scope beta. "
                "Radar se mantiene bajo demanda para evitar calculos pesados."
            ),
        },
        "valoria_index": valoria_index,
        "diagnostics": {
            "active_apartments": active_count,
            "fresh_apartments": fresh_count,
            "stale_listings": dataset.stale_count,
            "removed_or_inactive": dataset.removed_or_inactive_count,
            "missing_url": dataset.missing_url_count,
            "new_listings_24h": dataset.new_listings_24h,
            "new_listings_7d": dataset.new_listings_7d,
            "removed_7d": dataset.removed_7d,
            "price_changes_30d": dataset.price_changes_30d,
        },
        "updated_at": dataset.now,
        "source": "listings_db",
    }


async def build_liquidity_summary(
    session: AsyncSession,
    *,
    max_staleness_days: int = 7,
) -> dict[str, Any]:
    dataset = await _load_market_dataset(session, max_staleness_days=max_staleness_days)
    active_count = len(dataset.active)
    if active_count == 0:
        return liquidity_summary_placeholder(status="empty")

    fresh_count = len(dataset.fresh)
    markets_with_depth = sum(
        1 for count in _counts_by_comuna(dataset.active).values() if count >= 20
    )
    freshness_ratio = _ratio(fresh_count, active_count)
    depth_quality = min(active_count / 1000, 1.0)
    market_depth_quality = min(markets_with_depth / 10, 1.0)
    price_change_quality = min(dataset.price_changes_30d / 100, 1.0)

    score = round(
        100
        * (
            0.40 * depth_quality
            + 0.30 * freshness_ratio
            + 0.20 * market_depth_quality
            + 0.10 * price_change_quality
        )
    )
    has_price_history = dataset.price_changes_30d > 0
    return {
        "status": "partial" if not has_price_history else _market_status(active_count),
        "available": True,
        "value": _clamp_score(score),
        "max": 100,
        "label": "Liquidez del mercado",
        "message": (
            "Proxy v0 basado en profundidad de oferta, frescura y cambios de precio."
            if has_price_history
            else "Proxy v0 basado en profundidad de oferta y frescura de publicaciones."
        ),
        "diagnostics": {
            "active_listings": active_count,
            "fresh_listings": fresh_count,
            "new_listings_7d": dataset.new_listings_7d,
            "removed_7d": dataset.removed_7d,
            "price_changes_30d": dataset.price_changes_30d,
            "comunas_with_depth": markets_with_depth,
        },
        "source": "listings_price_history_db" if has_price_history else "listings_db",
    }


async def build_microzones_summary(
    session: AsyncSession,
    *,
    max_staleness_days: int = 7,
    limit: int = 5,
) -> dict[str, Any]:
    dataset = await _load_market_dataset(session, max_staleness_days=max_staleness_days)
    if not dataset.active:
        return microzones_summary_placeholder(status="empty")

    fine_groups = _group_listings(dataset.active, level="microzone")
    groups = {key: rows for key, rows in fine_groups.items() if len(rows) >= 10}
    group_type = "microzone"
    if not groups:
        groups = _group_listings(dataset.active, level="comuna")
        group_type = "comuna_proxy"

    items = [
        _microzone_item(key, rows, dataset.fresh, group_type=group_type)
        for key, rows in groups.items()
    ]
    items.sort(key=lambda item: (item["score"] or 0, item["active_listings"]), reverse=True)
    status = "available" if group_type == "microzone" else "partial"
    return {
        "status": status,
        "available": True,
        "items": items[:limit],
        "message": (
            "Proxy v0 basado en microzona declarada en metadata."
            if group_type == "microzone"
            else "Fallback comunal; microzona fina pendiente."
        ),
        "source": "listings_raw_metadata_db" if group_type == "microzone" else "listings_db",
    }


def market_briefing_placeholder(status: str = "coming_soon") -> dict[str, Any]:
    """Return an honest market briefing contract without synthetic metrics."""
    is_empty = status == "empty"
    return {
        "status": "empty" if is_empty else "coming_soon",
        "available": False,
        "market": "Santiago, Chile",
        "headline": "Sin senales activas suficientes" if is_empty else "Briefing de mercado en preparacion",
        "summary": (
            "No hay departamentos activos suficientes para calcular senales v0."
            if is_empty
            else "Se activara cuando exista contrato real de mercado, liquidez y tendencia."
        ),
        "indicators": [
            {
                "key": "active_supply",
                "label": "Oferta en mercado",
                "status": "empty" if is_empty else "coming_soon",
                "value": 0 if is_empty else None,
                "delta_pct": None,
                "unit": "publicaciones" if is_empty else None,
                "description": "Departamentos activos en el scope beta.",
            },
            {
                "key": "fresh_listings",
                "label": "Publicaciones vigentes",
                "status": "empty" if is_empty else "coming_soon",
                "value": 0 if is_empty else None,
                "delta_pct": None,
                "unit": "confirmadas" if is_empty else None,
                "description": "Publicaciones activas confirmadas recientemente.",
            },
            {
                "key": "new_listings_7d",
                "label": "Nuevas publicaciones",
                "status": "empty" if is_empty else "coming_soon",
                "value": 0 if is_empty else None,
                "delta_pct": None,
                "unit": "7 dias" if is_empty else None,
                "description": "Publicaciones nuevas detectadas en los ultimos 7 dias.",
            },
        ],
        "insight": {
            "status": "empty" if is_empty else "coming_soon",
            "text": (
                "Sin datos activos suficientes; Valoria no inventa metricas."
                if is_empty
                else "Sin metricas simuladas: Valoria mostrara insights cuando existan senales publicables."
            ),
        },
        "valoria_index": valoria_index_placeholder(status=status),
        "diagnostics": {
            "active_apartments": 0,
            "fresh_apartments": 0,
            "stale_listings": 0,
            "removed_or_inactive": 0,
            "missing_url": 0,
            "new_listings_24h": 0,
            "new_listings_7d": 0,
            "removed_7d": 0,
            "price_changes_30d": 0,
        },
        "updated_at": None,
        "source": "listings_db_empty" if is_empty else "valoria_market_contract_placeholder",
    }


def valoria_index_placeholder(status: str = "coming_soon") -> dict[str, Any]:
    is_empty = status == "empty"
    return {
        "status": "empty" if is_empty else "coming_soon",
        "available": False,
        "value": None,
        "max": 100,
        "label": "Indice Valoria",
        "confidence_label": "Sin datos" if is_empty else "Esperando contrato",
        "description": (
            "Indice de salud de datos Valoria, no senal de precio."
            if is_empty
            else "Esperando contrato de mercado para publicar una senal agregada."
        ),
        "source": "listings_db_empty" if is_empty else "valoria_index_contract_placeholder",
    }


def microzones_summary_placeholder(status: str = "coming_soon") -> dict[str, Any]:
    is_empty = status == "empty"
    return {
        "status": "empty" if is_empty else "coming_soon",
        "available": False,
        "items": [],
        "message": (
            "Sin departamentos activos para calcular microzonas v0."
            if is_empty
            else "Microzonas en preparacion. Se activara cuando exista senal de microzona publicable para el dashboard."
        ),
        "source": "listings_db_empty" if is_empty else "microzone_contract_placeholder",
    }


def liquidity_summary_placeholder(status: str = "coming_soon") -> dict[str, Any]:
    is_empty = status == "empty"
    return {
        "status": "empty" if is_empty else "coming_soon",
        "available": False,
        "value": None,
        "max": 100,
        "label": "Liquidez del mercado",
        "message": (
            "Sin departamentos activos para calcular liquidez v0."
            if is_empty
            else "Requiere contrato de liquidez por mercado."
        ),
        "diagnostics": {
            "active_listings": 0,
            "fresh_listings": 0,
            "new_listings_7d": 0,
            "removed_7d": 0,
            "price_changes_30d": 0,
            "comunas_with_depth": 0,
        },
        "source": "listings_db_empty" if is_empty else "liquidity_contract_placeholder",
    }


async def _load_market_dataset(
    session: AsyncSession,
    *,
    max_staleness_days: int,
) -> MarketDataset:
    now = datetime.now(UTC)
    rows = await session.scalars(
        select(ListingORM).where(ListingORM.property_type == BETA_PROPERTY_TYPE)
    )
    scoped = [_to_listing_signal(row) for row in rows.all()]
    active = [listing for listing in scoped if listing.status == "active"]
    freshness_config = RadarFreshnessConfig(
        require_fresh_listings=True,
        max_listing_staleness_days=max_staleness_days,
        exclude_refresh_failed=True,
        exclude_removed_or_unavailable=True,
    )
    freshness_decisions = [
        (listing, is_fresh_for_radar(_to_domain_listing(listing), now=now, config=freshness_config))
        for listing in active
    ]
    fresh = [listing for listing, decision in freshness_decisions if decision.allowed]
    stale_count = sum(
        1 for _listing, decision in freshness_decisions if decision.cause in {"stale", "missing_freshness"}
    )
    missing_url_count = sum(
        1 for _listing, decision in freshness_decisions if decision.cause == "missing_url"
    )
    removed_or_inactive_count = sum(1 for listing in scoped if listing.status != "active") + sum(
        1 for _listing, decision in freshness_decisions if decision.cause == "removed_or_unavailable"
    )
    new_listings_24h = _new_listings_count(scoped, now=now, days=1)
    new_listings_7d = _new_listings_count(scoped, now=now, days=7)
    removed_7d = _removed_recent_count(scoped, now=now, days=7)
    price_changes_30d = await _price_changes_30d(session, now=now)
    return MarketDataset(
        now=now,
        scoped=scoped,
        active=active,
        fresh=fresh,
        stale_count=stale_count,
        missing_url_count=missing_url_count,
        removed_or_inactive_count=removed_or_inactive_count,
        new_listings_24h=new_listings_24h,
        new_listings_7d=new_listings_7d,
        removed_7d=removed_7d,
        price_changes_30d=price_changes_30d,
    )


async def _price_changes_30d(session: AsyncSession, *, now: datetime) -> int:
    cutoff = now - timedelta(days=30)
    rows = await session.scalars(
        select(PriceHistoryORM.id)
        .join(ListingORM, ListingORM.id == PriceHistoryORM.listing_id)
        .where(
            ListingORM.property_type == BETA_PROPERTY_TYPE,
            PriceHistoryORM.observed_at >= cutoff,
            PriceHistoryORM.is_artifact.is_(False),
        )
    )
    return len(rows.all())


def _to_listing_signal(row: ListingORM) -> ListingSignal:
    return ListingSignal(
        id=row.id,
        comuna=row.comuna,
        status=row.status,
        price_uf=float(row.price_uf) if row.price_uf is not None else None,
        price_uf_confidence=row.price_uf_confidence,
        url=row.url,
        usable_area_m2=row.usable_area_m2,
        built_area_m2=row.built_area_m2,
        m2=row.m2,
        geocode_precision=row.geocode_precision,
        raw_metadata=row.raw_metadata or {},
        scraped_at=row.scraped_at,
        last_seen_at=row.last_seen_at,
        last_refresh_attempted_at=row.last_refresh_attempted_at,
        last_refresh_status=row.last_refresh_status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _build_valoria_index(dataset: MarketDataset) -> dict[str, Any]:
    active_count = len(dataset.active)
    price_quality = _ratio(sum(1 for row in dataset.active if _has_reliable_price(row)), active_count)
    area_quality = _ratio(sum(1 for row in dataset.active if _usable_area(row) is not None), active_count)
    geo_quality = _ratio(sum(1 for row in dataset.active if _has_good_geocode(row)), active_count)
    freshness_quality = _ratio(len(dataset.fresh), active_count)
    depth_quality = min(active_count / 1000, 1.0)
    value = round(
        100
        * (
            0.30 * price_quality
            + 0.20 * area_quality
            + 0.25 * geo_quality
            + 0.15 * freshness_quality
            + 0.10 * depth_quality
        )
    )
    status = _market_status(active_count)
    return {
        "status": status,
        "available": True,
        "value": _clamp_score(value),
        "max": 100,
        "label": "Indice Valoria",
        "confidence_label": "Proxy v0" if status == "partial" else "Datos reales v0",
        "description": "Indice de salud de datos Valoria, no senal de precio.",
        "source": "listings_db_quality_proxy_v0",
    }


def _microzone_item(
    key: tuple[str, str],
    rows: list[ListingSignal],
    fresh_rows: list[ListingSignal],
    *,
    group_type: str,
) -> dict[str, Any]:
    group_key, name = key
    row_ids = {row.id for row in rows}
    fresh_count = sum(1 for row in fresh_rows if row.id in row_ids)
    active_count = len(rows)
    price_area_values = [
        row.price_uf / area
        for row in rows
        if row.price_uf is not None and (area := _usable_area(row)) is not None
    ]
    depth_quality = min(active_count / 50, 1.0)
    freshness_quality = _ratio(fresh_count, active_count)
    price_area_quality = _ratio(len(price_area_values), active_count)
    geo_quality = _ratio(sum(1 for row in rows if _has_good_geocode(row)), active_count)
    score = round(
        100
        * (
            0.35 * depth_quality
            + 0.25 * freshness_quality
            + 0.25 * price_area_quality
            + 0.15 * geo_quality
        )
    )
    confidence = "low"
    if group_type == "microzone" and active_count >= 20 and len(price_area_values) >= 10:
        confidence = "medium"
    if group_type == "microzone" and active_count >= 50 and len(price_area_values) >= 25:
        confidence = "high"

    return {
        "id": group_key,
        "name": name,
        "type": group_type,
        "status": "available" if group_type == "microzone" else "partial",
        "score": _clamp_score(score),
        "variation_pct": None,
        "active_listings": active_count,
        "fresh_listings": fresh_count,
        "median_price_m2_uf": round(median(price_area_values), 1) if price_area_values else None,
        "confidence": confidence,
        "note": (
            "Proxy v0 basado en publicaciones activas con precio UF y superficie."
            if group_type == "microzone"
            else "Fallback comunal; microzona fina pendiente."
        ),
    }


def _group_listings(
    rows: list[ListingSignal],
    *,
    level: str,
) -> dict[tuple[str, str], list[ListingSignal]]:
    groups: dict[tuple[str, str], list[ListingSignal]] = defaultdict(list)
    for row in rows:
        if level == "microzone":
            value = _metadata_microzone(row.raw_metadata)
            if value is None:
                continue
            name = str(value).strip()
        else:
            name = row.comuna.strip()
        if not name:
            continue
        groups[(_slug(name), _display_name(name))].append(row)
    return groups


def _metadata_microzone(raw_metadata: dict[str, Any]) -> Any | None:
    for key in MICROZONE_KEYS:
        value = raw_metadata.get(key)
        if value:
            return value
    location = raw_metadata.get("location")
    if isinstance(location, dict):
        for key in MICROZONE_KEYS:
            value = location.get(key)
            if value:
                return value
    return None


def _counts_by_comuna(rows: list[ListingSignal]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row.comuna] += 1
    return counts


def _new_listings_count(rows: list[ListingSignal], *, now: datetime, days: int) -> int:
    cutoff = now - timedelta(days=days)
    return sum(
        1
        for row in rows
        if (first_seen := _first_seen_at(row)) is not None and first_seen >= cutoff
    )


def _removed_recent_count(rows: list[ListingSignal], *, now: datetime, days: int) -> int:
    cutoff = now - timedelta(days=days)
    return sum(
        1
        for row in rows
        if row.status != "active"
        and (last_change := _as_aware_utc(row.updated_at) or _as_aware_utc(row.last_seen_at))
        is not None
        and last_change >= cutoff
    )


def _first_seen_at(row: ListingSignal) -> datetime | None:
    return _as_aware_utc(row.created_at) or _as_aware_utc(row.scraped_at)


def _to_domain_listing(row: ListingSignal) -> Listing:
    price_clp = Decimal(str(row.price_uf or 0)) * Decimal("40000")
    return Listing(
        id=row.id,
        source="dashboard_summary",
        external_id=None,
        title="dashboard summary listing",
        comuna=row.comuna,
        m2=row.m2,
        bedrooms=0,
        bathrooms=0,
        parking=0,
        price=Price.from_clp(price_clp),
        status=row.status,
        fingerprint=f"dashboard-summary-{row.id or row.comuna}",
        scraped_at=row.scraped_at,
        last_seen_at=row.last_seen_at,
        last_refresh_attempted_at=row.last_refresh_attempted_at,
        last_refresh_status=row.last_refresh_status,
        url=row.url,
        property_type=BETA_PROPERTY_TYPE,
        built_area_m2=row.built_area_m2,
        usable_area_m2=row.usable_area_m2,
        geocode_precision=row.geocode_precision,
        price_uf=Decimal(str(row.price_uf)) if row.price_uf is not None else None,
        price_uf_confidence=row.price_uf_confidence,
        raw_metadata=row.raw_metadata,
    )


def _has_reliable_price(row: ListingSignal) -> bool:
    if row.price_uf is None or row.price_uf <= 0:
        return False
    confidence = (row.price_uf_confidence or "").strip().lower()
    return not confidence or confidence in RELIABLE_PRICE_UF_CONFIDENCE


def _usable_area(row: ListingSignal) -> float | None:
    for value in (row.usable_area_m2, row.built_area_m2, row.m2):
        if value is not None and value > 0:
            return value
    return None


def _has_good_geocode(row: ListingSignal) -> bool:
    return (row.geocode_precision or "").strip().lower() in GOOD_GEOCODE_PRECISIONS


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return max(0.0, min(numerator / denominator, 1.0))


def _market_status(active_count: int) -> str:
    return "available" if active_count >= 50 else "partial"


def _clamp_score(value: int | float) -> int:
    return max(0, min(round(value), 100))


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _slug(value: str) -> str:
    return (
        value.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
    )


def _display_name(value: str) -> str:
    cleaned = value.strip().replace("_", " ")
    return " ".join(part.capitalize() for part in cleaned.split())
