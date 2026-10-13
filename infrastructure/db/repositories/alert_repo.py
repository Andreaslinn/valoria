"""Repositorio SQLAlchemy para alertas persistentes."""
from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from infrastructure.db.models import AlertORM, AlertReadORM, SavedListingORM


class SqlAlchemyAlertRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_alert(
        self,
        *,
        listing_id: int,
        alert_type: str,
        payload: dict[str, Any] | None = None,
    ) -> AlertORM:
        alert = AlertORM(
            listing_id=listing_id,
            alert_type=alert_type,
            payload=_json_safe(payload or {}),
        )
        self._session.add(alert)
        await self._session.flush()
        await self._session.refresh(alert)
        return alert

    async def get_unread_alerts(self, *, limit: int = 50) -> list[AlertORM]:
        stmt = (
            select(AlertORM)
            .where(AlertORM.is_read.is_(False))
            .order_by(AlertORM.created_at.desc(), AlertORM.id.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def alert_exists_recently(
        self,
        *,
        listing_id: int,
        alert_type: str,
        since: datetime | None = None,
    ) -> bool:
        cutoff = since or (datetime.now(UTC) - timedelta(hours=24))
        stmt = (
            select(AlertORM.id)
            .where(AlertORM.listing_id == listing_id)
            .where(AlertORM.alert_type == alert_type)
            .where(AlertORM.created_at >= cutoff)
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def existing_alert_listing_ids(
        self,
        *,
        listing_ids: Iterable[int],
        alert_type: str,
        since: datetime | None = None,
    ) -> set[int]:
        ids = {int(listing_id) for listing_id in listing_ids}
        if not ids:
            return set()
        cutoff = since or (datetime.now(UTC) - timedelta(hours=24))
        stmt = (
            select(AlertORM.listing_id)
            .where(AlertORM.listing_id.in_(ids))
            .where(AlertORM.alert_type == alert_type)
            .where(AlertORM.created_at >= cutoff)
        )
        return {int(row[0]) for row in (await self._session.execute(stmt)).all()}

    async def price_drop_event_exists(
        self,
        *,
        listing_id: int,
        previous_price_uf: int | float | Decimal | None = None,
        new_price_uf: int | float | Decimal | None = None,
        previous_price_clp_snapshot: int | float | Decimal | None = None,
        new_price_clp_snapshot: int | float | Decimal | None = None,
        change_basis: str | None = None,
        since: datetime | None = None,
    ) -> bool:
        cutoff = since or (datetime.now(UTC) - timedelta(hours=24))
        stmt = (
            select(AlertORM.payload)
            .where(AlertORM.listing_id == listing_id)
            .where(AlertORM.alert_type == "price_drop")
            .where(AlertORM.created_at >= cutoff)
        )
        for (payload,) in (await self._session.execute(stmt)).all():
            if _price_drop_payload_matches(
                payload,
                previous_price_uf=previous_price_uf,
                new_price_uf=new_price_uf,
                previous_price_clp_snapshot=previous_price_clp_snapshot,
                new_price_clp_snapshot=new_price_clp_snapshot,
                change_basis=change_basis,
            ):
                return True
        return False

    async def get_unread_alerts_for_user_saved_listings(
        self,
        *,
        user_id: int,
        limit: int = 50,
        include_read: bool = False,
    ) -> list[AlertORM]:
        stmt = (
            select(AlertORM, AlertReadORM.alert_id)
            .join(SavedListingORM, SavedListingORM.listing_id == AlertORM.listing_id)
            .outerjoin(AlertReadORM, and_(AlertReadORM.alert_id == AlertORM.id, AlertReadORM.user_id == user_id))
            .options(joinedload(AlertORM.listing))
            .where(SavedListingORM.user_id == user_id)
            .where(SavedListingORM.status == "active")
            .order_by(AlertORM.created_at.desc(), AlertORM.id.desc())
            .limit(limit)
        )
        if not include_read:
            stmt = stmt.where(AlertORM.is_read.is_(False), AlertReadORM.alert_id.is_(None))
        rows = (await self._session.execute(stmt)).all()
        for alert, read_id in rows:
            alert._user_is_read = alert.is_read or read_id is not None
        return [alert for alert, _ in rows]

    async def mark_alert_as_read(self, *, alert_id: int, user_id: int) -> AlertORM | None:
        stmt = (
            select(AlertORM)
            .join(SavedListingORM, SavedListingORM.listing_id == AlertORM.listing_id)
            .options(joinedload(AlertORM.listing))
            .where(AlertORM.id == alert_id)
            .where(SavedListingORM.user_id == user_id)
            .where(SavedListingORM.status == "active")
        )
        alert = (await self._session.execute(stmt)).scalar_one_or_none()
        if alert is None:
            return None
        if self._session.get_bind().dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        else:
            from sqlalchemy.dialects.postgresql import insert
        await self._session.execute(insert(AlertReadORM).values(user_id=user_id, alert_id=alert_id).on_conflict_do_nothing())
        alert._user_is_read = True
        return alert


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _price_drop_payload_matches(
    payload: Any,
    *,
    previous_price_uf: int | float | Decimal | None,
    new_price_uf: int | float | Decimal | None,
    previous_price_clp_snapshot: int | float | Decimal | None,
    new_price_clp_snapshot: int | float | Decimal | None,
    change_basis: str | None,
) -> bool:
    if not isinstance(payload, dict):
        return False
    basis = _normalized_basis(change_basis)
    if basis == "uf":
        return (
            _payload_basis(payload) == "uf"
            and _payload_decimal(payload.get("previous_price_uf")) == _payload_decimal(previous_price_uf)
            and _payload_decimal(payload.get("new_price_uf")) == _payload_decimal(new_price_uf)
        )
    if basis in {"clp", "clp_legacy"}:
        return (
            _payload_basis(payload) in {basis, "clp_legacy" if basis == "clp" else "clp"}
            and _payload_int(payload.get("previous_price_clp_snapshot") or payload.get("previous_price_clp"))
            == _payload_int(previous_price_clp_snapshot)
            and _payload_int(payload.get("new_price_clp_snapshot") or payload.get("new_price_clp"))
            == _payload_int(new_price_clp_snapshot)
        )
    return False


def _payload_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _payload_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        return None


def _normalized_basis(value: str | None) -> str | None:
    text = str(value or "").strip().lower()
    if text.startswith("uf"):
        return "uf"
    if text.startswith("clp"):
        return "clp_legacy" if "legacy" in text else "clp"
    return text or None


def _payload_basis(payload: dict[str, Any]) -> str | None:
    basis = _normalized_basis(str(payload.get("change_basis") or ""))
    if basis is not None:
        return basis
    unit = str(payload.get("canonical_price_unit") or payload.get("price_currency") or "").strip().upper()
    if unit == "UF":
        return "uf"
    if unit == "CLP":
        return "clp"
    return None
