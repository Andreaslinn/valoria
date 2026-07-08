"""Portfolio comparisons service backed by real watchlist/listing data."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from infrastructure.db.models import (
    AlertORM,
    PortfolioComparisonItemORM,
    PortfolioComparisonORM,
    PortfolioItemValuationSnapshotORM,
    SavedListingORM,
)
from services.portfolio_comparison_report import build_portfolio_comparison_report_html

PORTFOLIO_COMPARISON_MIN_ITEMS = 2
PORTFOLIO_COMPARISON_MAX_ITEMS = 4


class PortfolioComparisonError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class PortfolioComparisonService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_comparison(self, *, user_id: int, title: str | None = None) -> dict[str, Any]:
        comparison = PortfolioComparisonORM(
            user_id=user_id,
            title=(title or "Comparacion de Portafolio").strip() or "Comparacion de Portafolio",
            status="draft",
        )
        self._session.add(comparison)
        await self._session.flush()
        await self._session.commit()
        return await self.get_comparison(user_id=user_id, comparison_id=comparison.id)

    async def list_comparisons(self, *, user_id: int) -> list[dict[str, Any]]:
        stmt = (
            select(PortfolioComparisonORM)
            .options(selectinload(PortfolioComparisonORM.items))
            .where(PortfolioComparisonORM.user_id == user_id)
            .order_by(PortfolioComparisonORM.updated_at.desc(), PortfolioComparisonORM.id.desc())
        )
        comparisons = (await self._session.execute(stmt)).scalars().all()
        return [self._summary_payload(comparison) for comparison in comparisons]

    async def get_comparison(self, *, user_id: int, comparison_id: int) -> dict[str, Any]:
        comparison = await self._get_owned_comparison(user_id=user_id, comparison_id=comparison_id)
        snapshots = await self._latest_snapshots(user_id, tuple(item.listing_id for item in comparison.items))
        alerts = await self._alert_counts(user_id, tuple(item.listing_id for item in comparison.items))
        return {
            "comparison": self._summary_payload(comparison),
            "items": [
                _item_payload(item, snapshot=snapshots.get(item.listing_id), alert_count=alerts.get(item.listing_id, 0))
                for item in comparison.items
            ],
        }

    async def add_item(
        self,
        *,
        user_id: int,
        comparison_id: int,
        listing_id: int | None = None,
        watchlist_item_id: int | None = None,
    ) -> dict[str, Any]:
        comparison = await self._get_owned_comparison(user_id=user_id, comparison_id=comparison_id)
        if len(comparison.items) >= PORTFOLIO_COMPARISON_MAX_ITEMS:
            raise PortfolioComparisonError("La comparacion permite maximo 4 propiedades.")
        saved = await self._owned_watchlist_item(
            user_id=user_id,
            listing_id=listing_id,
            watchlist_item_id=watchlist_item_id,
        )
        if any(item.listing_id == saved.listing_id for item in comparison.items):
            raise PortfolioComparisonError("La propiedad ya esta en esta comparacion.")
        position = len(comparison.items) + 1
        comparison.items.append(
            PortfolioComparisonItemORM(
                listing_id=saved.listing_id,
                watchlist_item_id=saved.id,
                position=position,
            )
        )
        comparison.updated_at = datetime.now(UTC)
        await self._session.flush()
        await self._session.commit()
        return await self.get_comparison(user_id=user_id, comparison_id=comparison.id)

    async def remove_item(self, *, user_id: int, comparison_id: int, item_id: int) -> dict[str, Any]:
        comparison = await self._get_owned_comparison(user_id=user_id, comparison_id=comparison_id)
        item = next((current for current in comparison.items if current.id == item_id), None)
        if item is None:
            raise PortfolioComparisonError("Item de comparacion no encontrado.", status_code=404)
        await self._session.delete(item)
        await self._session.flush()
        remaining = sorted(comparison.items, key=lambda current: current.position)
        for index, current in enumerate((current for current in remaining if current.id != item_id), start=1):
            current.position = index
        comparison.updated_at = datetime.now(UTC)
        await self._session.commit()
        return await self.get_comparison(user_id=user_id, comparison_id=comparison.id)

    async def build_report_html(self, *, user_id: int, comparison_id: int) -> str:
        detail = await self.get_comparison(user_id=user_id, comparison_id=comparison_id)
        if len(detail["items"]) < PORTFOLIO_COMPARISON_MIN_ITEMS:
            raise PortfolioComparisonError("La comparacion necesita al menos 2 propiedades.", status_code=400)
        return build_portfolio_comparison_report_html(detail)

    async def _get_owned_comparison(self, *, user_id: int, comparison_id: int) -> PortfolioComparisonORM:
        stmt = (
            select(PortfolioComparisonORM)
            .options(
                selectinload(PortfolioComparisonORM.items).joinedload(PortfolioComparisonItemORM.listing),
                selectinload(PortfolioComparisonORM.items).joinedload(PortfolioComparisonItemORM.watchlist_item),
            )
            .where(PortfolioComparisonORM.id == comparison_id)
            .where(PortfolioComparisonORM.user_id == user_id)
        )
        comparison = (await self._session.execute(stmt)).scalar_one_or_none()
        if comparison is None:
            raise PortfolioComparisonError("Comparacion no encontrada.", status_code=404)
        return comparison

    async def _owned_watchlist_item(
        self,
        *,
        user_id: int,
        listing_id: int | None,
        watchlist_item_id: int | None,
    ) -> SavedListingORM:
        stmt = (
            select(SavedListingORM)
            .options(joinedload(SavedListingORM.listing))
            .where(SavedListingORM.user_id == user_id)
            .where(SavedListingORM.status == "active")
        )
        if watchlist_item_id is not None:
            stmt = stmt.where(SavedListingORM.id == watchlist_item_id)
        elif listing_id is not None:
            stmt = stmt.where(SavedListingORM.listing_id == listing_id)
        else:
            raise PortfolioComparisonError("Debes indicar listing_id o watchlist_item_id.")
        saved = (await self._session.execute(stmt)).scalar_one_or_none()
        if saved is None:
            raise PortfolioComparisonError("La propiedad no pertenece a tu watchlist activa.", status_code=403)
        return saved

    async def _latest_snapshots(
        self,
        user_id: int,
        listing_ids: tuple[int, ...],
    ) -> dict[int, PortfolioItemValuationSnapshotORM]:
        if not listing_ids:
            return {}
        stmt = (
            select(PortfolioItemValuationSnapshotORM)
            .where(PortfolioItemValuationSnapshotORM.user_id == user_id)
            .where(PortfolioItemValuationSnapshotORM.listing_id.in_(listing_ids))
            .order_by(
                PortfolioItemValuationSnapshotORM.snapshot_at.desc(),
                PortfolioItemValuationSnapshotORM.id.desc(),
            )
        )
        snapshots: dict[int, PortfolioItemValuationSnapshotORM] = {}
        for snapshot in (await self._session.execute(stmt)).scalars().all():
            snapshots.setdefault(snapshot.listing_id, snapshot)
        return snapshots

    async def _alert_counts(self, user_id: int, listing_ids: tuple[int, ...]) -> dict[int, int]:
        if not listing_ids:
            return {}
        stmt = (
            select(AlertORM.listing_id, func.count(AlertORM.id))
            .join(SavedListingORM, SavedListingORM.listing_id == AlertORM.listing_id)
            .where(SavedListingORM.user_id == user_id)
            .where(AlertORM.listing_id.in_(listing_ids))
            .group_by(AlertORM.listing_id)
        )
        return {int(listing_id): int(count) for listing_id, count in (await self._session.execute(stmt)).all()}

    def _summary_payload(self, comparison: PortfolioComparisonORM) -> dict[str, Any]:
        item_count = len(comparison.items)
        return {
            "id": comparison.id,
            "user_id": comparison.user_id,
            "title": comparison.title,
            "status": "ready" if item_count >= PORTFOLIO_COMPARISON_MIN_ITEMS else comparison.status,
            "item_count": item_count,
            "is_ready": PORTFOLIO_COMPARISON_MIN_ITEMS <= item_count <= PORTFOLIO_COMPARISON_MAX_ITEMS,
            "created_at": _datetime(comparison.created_at),
            "updated_at": _datetime(comparison.updated_at),
        }


def _item_payload(
    item: PortfolioComparisonItemORM,
    *,
    snapshot: PortfolioItemValuationSnapshotORM | None,
    alert_count: int,
) -> dict[str, Any]:
    listing = item.listing
    price_uf = listing.price_uf if _price_basis(listing) == "canonical_uf" else None
    price_m2_uf = (price_uf / Decimal(str(listing.m2))) if price_uf is not None and listing.m2 else None
    avm_available = snapshot is not None and snapshot.valuation_status == "available" and snapshot.estimated_value_uf is not None
    delta_available = snapshot is not None and snapshot.delta_status == "available" and snapshot.delta_uf is not None
    return {
        "id": item.id,
        "listing_id": item.listing_id,
        "watchlist_item_id": item.watchlist_item_id,
        "position": item.position,
        "title": listing.title,
        "comuna": listing.comuna,
        "property_type": listing.property_type,
        "property_type_label": _property_type_label(listing.property_type),
        "m2": listing.m2,
        "m2_label": f"{listing.m2:g} m2" if listing.m2 else "No disponible",
        "bedrooms": listing.bedrooms,
        "bathrooms": listing.bathrooms,
        "rooms_label": _rooms_label(listing.bedrooms, listing.bathrooms),
        "published_price_clp": _decimal(listing.price_clp),
        "published_price_uf": _decimal(price_uf),
        "published_price_label": _price_label(price_uf, listing.price_clp),
        "price_basis": _price_basis(listing),
        "price_data_quality": _price_data_quality(listing),
        "price_m2_uf": _decimal(price_m2_uf),
        "price_m2_label": f"UF {_number(price_m2_uf)}/m2" if price_m2_uf is not None else "No disponible",
        "url": listing.url,
        "source": listing.source,
        "listing_status": listing.status,
        "avm": _avm_state(snapshot),
        "avm_label": f"UF {_number(snapshot.estimated_value_uf)}" if avm_available and snapshot else "No disponible",
        "delta": _delta_state(snapshot),
        "delta_label": _delta_label(snapshot) if delta_available and snapshot else "No disponible",
        "confidence": snapshot.confidence if avm_available and snapshot and snapshot.confidence else "No disponible",
        "alerts_count": alert_count,
        "alerts_label": str(alert_count) if alert_count else "No disponible",
        "data_freshness_status": snapshot.data_freshness_status if snapshot else "No disponible",
        "snapshot_at": _datetime(snapshot.snapshot_at) if snapshot else None,
    }


def _avm_state(snapshot: PortfolioItemValuationSnapshotORM | None) -> dict[str, Any]:
    if snapshot is None:
        return {"available": False, "status": "needs_snapshot", "reason": "needs_portfolio_avm_snapshot"}
    if snapshot.valuation_status != "available" or snapshot.estimated_value_uf is None:
        return {
            "available": False,
            "status": snapshot.valuation_status,
            "reason": snapshot.unavailable_reason or "needs_current_valuation",
        }
    return {
        "available": True,
        "status": "available",
        "estimated_value_uf": _decimal(snapshot.estimated_value_uf),
        "estimated_value_clp": _decimal(snapshot.estimated_value_clp),
        "lower_bound_uf": _decimal(snapshot.lower_bound_uf),
        "upper_bound_uf": _decimal(snapshot.upper_bound_uf),
        "confidence": snapshot.confidence,
        "snapshot_id": snapshot.id,
    }


def _delta_state(snapshot: PortfolioItemValuationSnapshotORM | None) -> dict[str, Any]:
    if snapshot is None:
        return {"available": False, "status": "needs_valuation", "reason": "needs_current_valuation"}
    if snapshot.delta_status != "available" or snapshot.delta_uf is None:
        return {
            "available": False,
            "status": snapshot.delta_status,
            "reason": snapshot.delta_unavailable_reason or "needs_canonical_price",
        }
    return {
        "available": True,
        "status": "available",
        "delta_uf": _decimal(snapshot.delta_uf),
        "delta_pct": snapshot.delta_pct,
        "snapshot_id": snapshot.id,
    }


def _price_basis(listing: Any) -> str:
    currency = str(listing.price_currency or "").strip().upper()
    if currency == "UF" and listing.price_uf is not None:
        return "canonical_uf"
    if currency == "CLP":
        return "canonical_clp"
    if currency == "UF":
        return "legacy_uf_missing_price_uf"
    return "legacy_unknown"


def _price_data_quality(listing: Any) -> str:
    if _price_basis(listing) == "canonical_uf":
        return str(listing.price_uf_source or listing.price_uf_confidence or "canonical_uf")
    if _price_basis(listing) == "canonical_clp":
        return "canonical_clp"
    return "legacy_unknown"


def _property_type_label(value: str) -> str:
    return {"apartment": "Departamento", "house": "Casa", "unknown": "Sin tipo"}.get(value, "Otro")


def _rooms_label(bedrooms: int | None, bathrooms: int | None) -> str:
    parts = []
    if bedrooms:
        parts.append(f"{bedrooms}D")
    if bathrooms:
        parts.append(f"{bathrooms}B")
    return " / ".join(parts) if parts else "No disponible"


def _price_label(price_uf: Decimal | None, price_clp: Decimal | None) -> str:
    if price_uf is not None:
        return f"UF {_number(price_uf)}"
    if price_clp is not None:
        return f"$ {_number(price_clp)}"
    return "No disponible"


def _delta_label(snapshot: PortfolioItemValuationSnapshotORM) -> str:
    pct = f"{snapshot.delta_pct:.1f}%".replace(".", ",") if snapshot.delta_pct is not None else "No disponible"
    return f"{pct} / UF {_number(snapshot.delta_uf)}"


def _decimal(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _number(value: Decimal | None) -> str:
    if value is None:
        return "No disponible"
    return f"{int(value):,}".replace(",", ".")


def _datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
