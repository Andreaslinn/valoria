"""Read-only v0 market intelligence summaries for the dashboard."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    usable_area_m2: float | None
    built_area_m2: float | None
    m2: float | None
    geocode_precision: str | None
    raw_metadata: dict[str, Any]
    scraped_at: datetime
    last_seen_at: datetime | None
    last_refresh_attempted_at: datetime | None
    last_refresh_status: str | None


@dataclass(frozen=True)
class MarketDataset:
    now: datetime
    active: list[ListingSignal]
    fresh: list[ListingSignal]
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
        "headline": "Mercado con senales activas disponibles",
        "summary": (
            "Valoria monitorea publicaciones activas, frescura y Radar bajo demanda."
        ),
        "indicators": [
            {
                "key": "supply",
                "label": "Oferta en mercado",
                "status": status,
                "value": active_count,
                "delta_pct": None,
                "unit": "listings",
                "description": "Departamentos activos dentro del scope beta.",
            },
            {
                "key": "freshness",
                "label": "Publicaciones vigentes",
                "status": status,
                "value": fresh_count,
                "delta_pct": None,
                "unit": "confirmed",
                "description": "Publicaciones confirmadas recientemente segun freshness.",
            },
            {
                "key": "opportunities",
                "label": "Radar",
                "status": "manual",
                "value": None,
                "delta_pct": None,
                "unit": None,
                "description": "Radar se ejecuta bajo demanda.",
            },
        ],
        "insight": {
            "status": status,
            "text": (
                "El dashboard prioriza publicaciones activas y confirmadas; Radar "
                "se mantiene manual para evitar calculos pesados."
            ),
        },
        "valoria_index": valoria_index,
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
            "price_changes_30d": dataset.price_changes_30d,
            "markets_with_depth": markets_with_depth,
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
                "key": "supply",
                "label": "Oferta en mercado",
                "status": "empty" if is_empty else "coming_soon",
                "value": 0 if is_empty else None,
                "delta_pct": None,
                "unit": "listings" if is_empty else None,
                "description": "Departamentos activos dentro del scope beta.",
            },
            {
                "key": "freshness",
                "label": "Publicaciones vigentes",
                "status": "empty" if is_empty else "coming_soon",
                "value": 0 if is_empty else None,
                "delta_pct": None,
                "unit": "confirmed" if is_empty else None,
                "description": "Publicaciones confirmadas recientemente segun freshness.",
            },
            {
                "key": "opportunities",
                "label": "Radar",
                "status": "manual",
                "value": None,
                "delta_pct": None,
                "unit": None,
                "description": "Radar se ejecuta bajo demanda.",
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
            "price_changes_30d": 0,
            "markets_with_depth": 0,
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
        select(ListingORM).where(
            ListingORM.property_type == BETA_PROPERTY_TYPE,
            ListingORM.status == "active",
        )
    )
    active = [_to_listing_signal(row) for row in rows.all()]
    cutoff = now - timedelta(days=max(max_staleness_days, 0))
    fresh = [listing for listing in active if _is_fresh_listing(listing, cutoff=cutoff)]
    price_changes_30d = await _price_changes_30d(session, now=now)
    return MarketDataset(
        now=now,
        active=active,
        fresh=fresh,
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
        usable_area_m2=row.usable_area_m2,
        built_area_m2=row.built_area_m2,
        m2=row.m2,
        geocode_precision=row.geocode_precision,
        raw_metadata=row.raw_metadata or {},
        scraped_at=row.scraped_at,
        last_seen_at=row.last_seen_at,
        last_refresh_attempted_at=row.last_refresh_attempted_at,
        last_refresh_status=row.last_refresh_status,
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


def _is_fresh_listing(row: ListingSignal, *, cutoff: datetime) -> bool:
    last_seen_at = _as_aware_utc(row.last_seen_at)
    if last_seen_at is not None and last_seen_at >= cutoff:
        return True
    refresh_at = _as_aware_utc(row.last_refresh_attempted_at)
    return refresh_at is not None and refresh_at >= cutoff and row.last_refresh_status == "ok"


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
