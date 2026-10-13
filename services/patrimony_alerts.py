"""Idempotent patrimony alert evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from infrastructure.db.models import (
    PatrimonyAlertORM,
    PatrimonyStrategyORM,
    PropertyAssetORM,
    PropertyValuationSnapshotORM,
    TerritorialDevelopmentORM,
)
from services.market_intelligence import MarketIntelligenceConfig, build_communes_summary
from services.patrimony import PatrimonyError

SELLER_FAVORABLE = {"prepare_sale", "favorable_market"}


@dataclass(frozen=True)
class AlertEvaluationResult:
    created: int
    existing: int


class PatrimonyAlertService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_alerts(self, *, user_id: int, unread_only: bool = True, include_dismissed: bool = False) -> list[PatrimonyAlertORM]:
        stmt = (
            select(PatrimonyAlertORM)
            .where(PatrimonyAlertORM.user_id == user_id)
            .options(
                selectinload(PatrimonyAlertORM.property),
                selectinload(PatrimonyAlertORM.strategy),
                selectinload(PatrimonyAlertORM.territorial_development),
            )
            .order_by(PatrimonyAlertORM.created_at.desc(), PatrimonyAlertORM.id.desc())
        )
        if unread_only:
            stmt = stmt.where(PatrimonyAlertORM.read_at.is_(None))
        if not include_dismissed:
            stmt = stmt.where(PatrimonyAlertORM.dismissed_at.is_(None))
        return list((await self._session.execute(stmt)).scalars().all())

    async def mark_read(self, *, user_id: int, alert_id: int) -> PatrimonyAlertORM:
        alert = await self._get_user_alert(user_id=user_id, alert_id=alert_id)
        alert.read_at = alert.read_at or datetime.now(UTC)
        await self._session.commit()
        return await self._get_user_alert(user_id=user_id, alert_id=alert_id)

    async def dismiss(self, *, user_id: int, alert_id: int) -> PatrimonyAlertORM:
        alert = await self._get_user_alert(user_id=user_id, alert_id=alert_id)
        now = datetime.now(UTC)
        alert.read_at = alert.read_at or now
        alert.dismissed_at = alert.dismissed_at or now
        await self._session.commit()
        return await self._get_user_alert(user_id=user_id, alert_id=alert_id)

    async def evaluate_user(self, *, user_id: int) -> AlertEvaluationResult:
        properties = await self._list_properties(user_id=user_id)
        strategies = await self._list_strategies(user_id=user_id)
        developments = await self._list_developments()
        commune_summary = await build_communes_summary(self._session, config=MarketIntelligenceConfig())
        created = 0
        existing = 0

        for asset in properties:
            for spec in self._property_alert_specs(asset, commune_summary):
                if await self._create_if_missing(user_id=user_id, **spec):
                    created += 1
                else:
                    existing += 1

        for strategy in strategies:
            for spec in self._strategy_alert_specs(strategy):
                if await self._create_if_missing(user_id=user_id, **spec):
                    created += 1
                else:
                    existing += 1

        for asset in properties:
            for development in developments:
                if not _matches_development(asset, development):
                    continue
                spec = _territorial_alert_spec(asset, development)
                if await self._create_if_missing(user_id=user_id, **spec):
                    created += 1
                else:
                    existing += 1

        await self._session.commit()
        return AlertEvaluationResult(created=created, existing=existing)

    async def _get_user_alert(self, *, user_id: int, alert_id: int) -> PatrimonyAlertORM:
        stmt = (
            select(PatrimonyAlertORM)
            .where(PatrimonyAlertORM.id == alert_id)
            .where(PatrimonyAlertORM.user_id == user_id)
            .options(
                selectinload(PatrimonyAlertORM.property),
                selectinload(PatrimonyAlertORM.strategy),
                selectinload(PatrimonyAlertORM.territorial_development),
            )
        )
        alert = (await self._session.execute(stmt)).scalar_one_or_none()
        if alert is None:
            raise PatrimonyError("Alerta no encontrada", status_code=404)
        return alert

    async def _create_if_missing(
        self,
        *,
        user_id: int,
        dedupe_key: str,
        alert_type: str,
        title: str,
        message: str,
        severity: str,
        metadata: dict[str, Any],
        property_asset_id: int | None = None,
        strategy_id: int | None = None,
        territorial_development_id: int | None = None,
    ) -> bool:
        existing = await self._session.scalar(
            select(PatrimonyAlertORM.id)
            .where(PatrimonyAlertORM.user_id == user_id)
            .where(PatrimonyAlertORM.dedupe_key == dedupe_key)
        )
        if existing is not None:
            return False
        self._session.add(
            PatrimonyAlertORM(
                user_id=user_id,
                property_asset_id=property_asset_id,
                strategy_id=strategy_id,
                territorial_development_id=territorial_development_id,
                alert_type=alert_type,
                title=title,
                message=message,
                severity=severity,
                metadata_=metadata,
                dedupe_key=dedupe_key,
            )
        )
        return True

    async def _list_properties(self, *, user_id: int) -> list[PropertyAssetORM]:
        stmt = (
            select(PropertyAssetORM)
            .where(PropertyAssetORM.user_id == user_id)
            .options(selectinload(PropertyAssetORM.valuation_snapshots))
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def _list_strategies(self, *, user_id: int) -> list[PatrimonyStrategyORM]:
        stmt = (
            select(PatrimonyStrategyORM)
            .where(PatrimonyStrategyORM.user_id == user_id)
            .options(selectinload(PatrimonyStrategyORM.property).selectinload(PropertyAssetORM.valuation_snapshots))
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def _list_developments(self) -> list[TerritorialDevelopmentORM]:
        stmt = select(TerritorialDevelopmentORM).where(TerritorialDevelopmentORM.is_active.is_(True))
        return list((await self._session.execute(stmt)).scalars().all())

    def _property_alert_specs(self, asset: PropertyAssetORM, commune_summary: dict[str, Any]) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        snapshots = _snapshots(asset)
        if snapshots:
            latest = snapshots[-1]
            if _aware(latest.snapshot_at) <= datetime.now(UTC) - timedelta(days=90):
                specs.append(
                    {
                        "property_asset_id": asset.id,
                        "alert_type": "valuation_refresh_due",
                        "title": "Tasacion pendiente de actualizacion",
                        "message": f"{asset.name} lleva 90 dias o mas sin una tasacion nueva.",
                        "severity": "medium",
                        "metadata": {"latest_snapshot_id": latest.id, "snapshot_at": latest.snapshot_at.isoformat()},
                        "dedupe_key": f"valuation_refresh_due:{asset.id}:{latest.id}",
                    }
                )
        if len(snapshots) >= 2:
            previous, latest = snapshots[-2], snapshots[-1]
            change_pct = _valuation_change_pct(previous, latest)
            if change_pct is not None and abs(change_pct) > Decimal("3"):
                specs.append(
                    {
                        "property_asset_id": asset.id,
                        "alert_type": "property_value_changed",
                        "title": "Cambio relevante de tasacion",
                        "message": f"La ultima tasacion de {asset.name} cambio mas de 3 % frente al snapshot anterior.",
                        "severity": "medium",
                        "metadata": {
                            "previous_snapshot_id": previous.id,
                            "latest_snapshot_id": latest.id,
                            "change_pct": float(round(change_pct, 2)),
                        },
                        "dedupe_key": f"property_value_changed:{asset.id}:{previous.id}:{latest.id}",
                    }
                )
        recommendation = _market_recommendation(asset, commune_summary)
        if recommendation:
            specs.append(
                {
                    "property_asset_id": asset.id,
                    "alert_type": "market_recommendation_changed",
                    "title": "Cambio de recomendacion patrimonial",
                    "message": f"La recomendacion patrimonial actual para {asset.name} es {recommendation}.",
                    "severity": "low",
                    "metadata": {"recommendation": recommendation},
                    "dedupe_key": f"market_recommendation_changed:{asset.id}:{recommendation}",
                }
            )
        if recommendation in SELLER_FAVORABLE:
            specs.append(
                {
                    "property_asset_id": asset.id,
                    "alert_type": "market_became_seller_favorable",
                    "title": "Mercado con senal favorable al vendedor",
                    "message": f"Las senales actuales de mercado sugieren preparar una revision para {asset.name}.",
                    "severity": "medium",
                    "metadata": {"recommendation": recommendation},
                    "dedupe_key": f"market_became_seller_favorable:{asset.id}:{recommendation}",
                }
            )
        return specs

    def _strategy_alert_specs(self, strategy: PatrimonyStrategyORM) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        latest = _snapshots(strategy.property)[-1] if _snapshots(strategy.property) else None
        if latest and strategy.target_value_uf and latest.estimated_value_uf and latest.estimated_value_uf >= strategy.target_value_uf:
            specs.append(
                {
                    "property_asset_id": strategy.property_asset_id,
                    "strategy_id": strategy.id,
                    "alert_type": "target_value_reached",
                    "title": "Precio objetivo alcanzado",
                    "message": f"{strategy.property.name} alcanzo o supero el precio objetivo definido.",
                    "severity": "high",
                    "metadata": {
                        "latest_snapshot_id": latest.id,
                        "latest_value_uf": float(latest.estimated_value_uf),
                        "target_value_uf": float(strategy.target_value_uf),
                    },
                    "dedupe_key": f"target_value_reached:{strategy.id}:{latest.id}:{strategy.target_value_uf}",
                }
            )
        review_days = _review_days(strategy)
        if _aware(strategy.updated_at) <= datetime.now(UTC) - timedelta(days=review_days):
            specs.append(
                {
                    "property_asset_id": strategy.property_asset_id,
                    "strategy_id": strategy.id,
                    "alert_type": "strategy_review_due",
                    "title": "Revision de estrategia pendiente",
                    "message": "La estrategia necesita una revision segun su horizonte y urgencia.",
                    "severity": "low",
                    "metadata": {"review_days": review_days, "updated_at": strategy.updated_at.isoformat()},
                    "dedupe_key": f"strategy_review_due:{strategy.id}:{strategy.updated_at.date().isoformat()}:{review_days}",
                }
            )
        return specs


def _territorial_alert_spec(asset: PropertyAssetORM, development: TerritorialDevelopmentORM) -> dict[str, Any]:
    return {
        "property_asset_id": asset.id,
        "territorial_development_id": development.id,
        "alert_type": "territorial_development_updated",
        "title": "Proyecto territorial actualizado",
        "message": f"{development.name} figura con estado {development.status} y aplica a {asset.name}.",
        "severity": "low",
        "metadata": {"development_status": development.status, "source_date": development.source_date.isoformat() if development.source_date else None},
        "dedupe_key": f"territorial_development_updated:{asset.id}:{development.id}:{development.status}:{development.updated_at.isoformat()}",
    }


def _snapshots(asset: PropertyAssetORM) -> list[PropertyValuationSnapshotORM]:
    return sorted(asset.valuation_snapshots, key=lambda item: (item.snapshot_at, item.id or 0))


def _valuation_change_pct(previous: PropertyValuationSnapshotORM, latest: PropertyValuationSnapshotORM) -> Decimal | None:
    if previous.estimated_value_uf is None or latest.estimated_value_uf is None or previous.estimated_value_uf <= 0:
        return None
    return ((latest.estimated_value_uf - previous.estimated_value_uf) / previous.estimated_value_uf) * Decimal("100")


def _market_recommendation(asset: PropertyAssetORM, commune_summary: dict[str, Any]) -> str | None:
    item = _commune_summary_item(commune_summary, asset.comuna)
    if not item:
        return None
    label = str(item.get("buyer_seller_balance") or item.get("market_balance_label") or "").lower()
    confidence = str(item.get("confidence") or "low").lower()
    price_drop_share = float(item.get("price_drop_share_30d") or 0)
    if confidence == "low":
        return "monitor"
    if "vendedor" in label:
        return "favorable_market" if price_drop_share < 0.08 else "prepare_sale"
    if "comprador" in label:
        return "evaluate_exit" if price_drop_share >= 0.12 else "monitor"
    return "maintain"


def _commune_summary_item(summary: dict[str, Any], comuna: str) -> dict[str, Any] | None:
    target = _normalize_key(comuna)
    for item in summary.get("items", []):
        if _normalize_key(str(item.get("comuna") or "")) == target:
            return item
    return None


def _matches_development(asset: PropertyAssetORM, development: TerritorialDevelopmentORM) -> bool:
    comuna = _normalize_key(asset.comuna)
    communes = {_normalize_key(value) for value in development.affected_communes or []}
    if comuna in communes:
        return True
    microzone = _normalize_key(str(asset.characteristics.get("microzone") or ""))
    microzones = {_normalize_key(value) for value in development.affected_microzones or []}
    return bool(microzone and microzone in microzones)


def _review_days(strategy: PatrimonyStrategyORM) -> int:
    if strategy.urgency == "high":
        return 14
    if strategy.horizon and "12" in strategy.horizon:
        return 60
    return 30


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalize_key(value: str) -> str:
    return " ".join(value.replace("_", " ").strip().lower().split())
