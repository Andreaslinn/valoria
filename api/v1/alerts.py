"""Authenticated real alert endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from api.deps import CurrentUser, DbSession
from infrastructure.db.models import AlertORM
from infrastructure.db.repositories import SqlAlchemyAlertRepository

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertOut(BaseModel):
    id: int
    listing_id: int
    alert_type: str
    message: str
    payload: dict[str, Any]
    created_at: datetime
    is_read: bool
    title: str | None = None
    comuna: str | None = None
    price_clp: int | None = None


class AlertReadOut(BaseModel):
    id: int
    is_read: bool


@router.get("", response_model=list[AlertOut])
async def list_alerts(
    current_user: CurrentUser,
    session: DbSession,
    limit: int = Query(default=50, ge=1, le=100),
    include_read: bool = False,
) -> list[AlertOut]:
    assert current_user.id is not None
    alerts = await SqlAlchemyAlertRepository(session).get_unread_alerts_for_user_saved_listings(
        user_id=current_user.id,
        limit=limit,
        include_read=include_read,
    )
    return [_alert_out(alert) for alert in alerts]


@router.post("/{alert_id}/read", response_model=AlertReadOut)
async def mark_alert_read(
    alert_id: int,
    current_user: CurrentUser,
    session: DbSession,
) -> AlertReadOut:
    assert current_user.id is not None
    repo = SqlAlchemyAlertRepository(session)
    alert = await repo.mark_alert_as_read(alert_id=alert_id, user_id=current_user.id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alerta no encontrada")
    await session.commit()
    return AlertReadOut(id=alert.id, is_read=getattr(alert, "_user_is_read", alert.is_read))


def _alert_out(alert: AlertORM) -> AlertOut:
    listing = alert.listing
    return AlertOut(
        id=alert.id,
        listing_id=alert.listing_id,
        alert_type=alert.alert_type,
        message=_alert_message(alert.alert_type, alert.payload),
        payload=alert.payload or {},
        created_at=alert.created_at,
        is_read=getattr(alert, "_user_is_read", alert.is_read),
        title=listing.title if listing is not None else None,
        comuna=listing.comuna if listing is not None else None,
        price_clp=int(listing.price_clp) if listing is not None else None,
    )


def _alert_message(alert_type: str, payload: dict[str, Any]) -> str:
    if alert_type == "price_drop":
        change_basis = str(payload.get("change_basis") or "").strip().lower()
        drop_pct = payload.get("drop_pct")
        if change_basis.startswith("uf"):
            previous_uf = payload.get("canonical_previous_price") or payload.get("previous_price_uf")
            new_uf = payload.get("canonical_new_price") or payload.get("new_price_uf")
            if previous_uf is not None and new_uf is not None and drop_pct is not None:
                message = (
                    f"La propiedad bajo de UF {_format_uf(previous_uf)} "
                    f"a UF {_format_uf(new_uf)} (-{float(drop_pct):.2f}%)."
                )
                previous_clp = payload.get("display_previous_price_clp") or payload.get("previous_price_clp_snapshot")
                new_clp = payload.get("display_new_price_clp") or payload.get("new_price_clp_snapshot")
                if previous_clp is not None and new_clp is not None:
                    message += (
                        f" Equivalente CLP snapshot: ${int(previous_clp):,} "
                        f"a ${int(new_clp):,}."
                    )
                return message
        previous_price = payload.get("canonical_previous_price") or payload.get("previous_price_clp_snapshot")
        new_price = payload.get("canonical_new_price") or payload.get("new_price_clp_snapshot")
        if previous_price is not None and new_price is not None and drop_pct is not None:
            return f"La propiedad bajo de ${int(previous_price):,} a ${int(new_price):,} (-{float(drop_pct):.2f}%)."
        return "La propiedad bajo de precio."
    return "Nueva alerta de la propiedad."


def _format_uf(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return f"{int(number):,}".replace(",", ".")
    return f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
