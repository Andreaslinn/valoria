"""Read-only recent user activity timeline for Tasar."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.db.models import UsageLogORM

ACTIVITY_STATUS_AVAILABLE = "available"
ACTIVITY_STATUS_EMPTY = "empty"
ACTIVITY_STATUS_PARTIAL = "partial"
ACTIVITY_STATUS_NOT_AVAILABLE = "not_available"

TASAR_USAGE_EVENT_TYPES = {
    "valuation_completed",
    "valuation_failed",
    "property_analysis_completed",
    "property_analysis_failed",
}


@dataclass(frozen=True)
class RecentUserActivityEvent:
    id: str
    event_type: str
    title: str
    description: str
    occurred_at: datetime
    source: str
    valuation_id: int | None = None
    listing_id: int | None = None
    report_id: int | None = None
    comuna: str | None = None
    property_type: str | None = None
    estimated_value_uf: float | None = None
    range_low_uf: float | None = None
    range_high_uf: float | None = None
    confidence: str | None = None
    status: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RecentUserActivity:
    status: str
    user_id: int
    events_count: int
    events: list[RecentUserActivityEvent]
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class RecentUserActivityService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_recent_activity(self, *, user_id: int, limit: int = 3) -> RecentUserActivity:
        if limit < 1:
            raise ValueError("limit debe ser mayor o igual a 1")
        rows = (
            await self._session.execute(
                select(UsageLogORM)
                .where(
                    UsageLogORM.user_id == user_id,
                    UsageLogORM.event_type.in_(TASAR_USAGE_EVENT_TYPES),
                )
                .order_by(desc(UsageLogORM.created_at), desc(UsageLogORM.id))
                .limit(max(limit * 4, limit))
            )
        ).scalars().all()

        events = [_activity_event_from_usage_log(row) for row in rows]
        events = [event for event in events if event is not None][:limit]
        if not events:
            return RecentUserActivity(
                status=ACTIVITY_STATUS_EMPTY,
                user_id=user_id,
                events_count=0,
                events=[],
                reasons=["no_tasar_user_activity_events"],
                warnings=[
                    "report_events_not_persisted",
                    "url_lookup_events_depend_on_product_usage_logs",
                ],
            )
        return RecentUserActivity(
            status=ACTIVITY_STATUS_PARTIAL,
            user_id=user_id,
            events_count=len(events),
            events=events,
            reasons=["usage_logs_available_for_tasar_activity"],
            warnings=["report_events_not_persisted"],
        )


def _activity_event_from_usage_log(row: UsageLogORM) -> RecentUserActivityEvent | None:
    payload = row.payload or {}
    metadata = payload.get("metadata") if isinstance(payload, dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}
    comuna = _clean_text(metadata.get("comuna"))
    property_type = _clean_text(metadata.get("property_type"))
    estimated_value_uf = _safe_float(metadata.get("estimated_value_uf"))
    range_low_uf = _safe_float(metadata.get("range_low_uf"))
    range_high_uf = _safe_float(metadata.get("range_high_uf"))
    confidence = _clean_text(metadata.get("confidence") or metadata.get("confidence_score"))
    if row.event_type == "valuation_completed":
        with_price = _safe_float(metadata.get("precio_publicado_uf")) is not None or _safe_float(
            metadata.get("precio_publicado_clp")
        ) is not None
        return RecentUserActivityEvent(
            id=f"usage:{row.id}",
            event_type="valuation_with_price" if with_price else "valuation_created",
            title="Tasaste con precio publicado" if with_price else "Tasaste una propiedad",
            description=_valuation_description(property_type, comuna, estimated_value_uf),
            occurred_at=row.created_at,
            source="usage_logs",
            comuna=comuna,
            property_type=property_type,
            estimated_value_uf=estimated_value_uf,
            range_low_uf=range_low_uf,
            range_high_uf=range_high_uf,
            confidence=confidence,
            status="completed",
        )
    if row.event_type == "property_analysis_completed":
        return RecentUserActivityEvent(
            id=f"usage:{row.id}",
            event_type="url_analysis_created",
            title="Analizaste una publicacion",
            description=_url_analysis_description(comuna),
            occurred_at=row.created_at,
            source="usage_logs",
            comuna=comuna,
            property_type=property_type,
            estimated_value_uf=estimated_value_uf,
            confidence=confidence,
            status="completed",
        )
    if row.event_type in {"valuation_failed", "property_analysis_failed"}:
        return RecentUserActivityEvent(
            id=f"usage:{row.id}",
            event_type="failed_or_partial_valuation",
            title="Tasacion incompleta",
            description=_failure_description(metadata),
            occurred_at=row.created_at,
            source="usage_logs",
            comuna=comuna,
            property_type=property_type,
            confidence=confidence,
            status="failed",
            reason=_clean_text(metadata.get("status") or metadata.get("error_status_code")),
        )
    return None


def _valuation_description(
    property_type: str | None,
    comuna: str | None,
    estimated_value_uf: float | None,
) -> str:
    prefix = " ".join(part for part in [_property_type_label(property_type), _comuna_label(comuna)] if part)
    if estimated_value_uf is not None:
        value = f"UF {_format_number(estimated_value_uf)}"
        return f"{prefix} · {value}" if prefix else value
    return prefix or "Tasacion real completada"


def _url_analysis_description(comuna: str | None) -> str:
    comuna_label = _comuna_label(comuna)
    return f"Publicacion en {comuna_label}" if comuna_label else "Publicacion analizada desde URL"


def _failure_description(metadata: dict[str, Any]) -> str:
    status = _clean_text(metadata.get("status"))
    if status:
        return status
    code = _clean_text(metadata.get("error_status_code"))
    if code:
        return f"No se completo la tasacion · error {code}"
    return "No se completo la tasacion"


def _property_type_label(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"apartment", "departamento", "depto"}:
        return "Departamento en"
    if normalized in {"house", "casa"}:
        return "Casa en"
    return "Propiedad en" if normalized else ""


def _comuna_label(value: str | None) -> str:
    text = (value or "").strip().replace("_", " ")
    return text.title() if text else ""


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:120] if text else None


def _format_number(value: float | Decimal) -> str:
    return f"{float(value):,.0f}".replace(",", ".")
