"""Patrimony property tracking service."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from infrastructure.db.models import (
    PatrimonyStrategyORM,
    PropertyAssetORM,
    PropertyValuationSnapshotORM,
    TerritorialDevelopmentORM,
)


class PatrimonyError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class PropertyAssetInput:
    name: str
    comuna: str
    property_type: str | None
    m2: float
    built_area_m2: float | None = None
    land_area_m2: float | None = None
    usable_area_m2: float | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    parking: int | None = None
    lat: float | None = None
    lon: float | None = None
    characteristics: dict[str, Any] | None = None


@dataclass(frozen=True)
class PropertyValuationSnapshotInput:
    estimated_value_uf: Decimal | None = None
    estimated_value_clp: Decimal | None = None
    lower_bound_uf: Decimal | None = None
    upper_bound_uf: Decimal | None = None
    lower_bound_clp: Decimal | None = None
    upper_bound_clp: Decimal | None = None
    confidence: str | None = None
    confidence_score: float | None = None
    engine_name: str | None = None
    engine_version: str | None = None
    engine_payload: dict[str, Any] | None = None
    snapshot_at: datetime | None = None


@dataclass(frozen=True)
class PatrimonyStrategyInput:
    property_asset_id: int
    objective: str
    horizon: str | None = None
    target_value_uf: Decimal | None = None
    urgency: str | None = None
    risk_profile: str | None = None
    next_move: str | None = None
    desired_property_type: str | None = None
    desired_communes: list[str] | None = None
    desired_budget_uf: Decimal | None = None


@dataclass(frozen=True)
class PatrimonyStrategyPatchInput:
    fields: set[str] = field(default_factory=set)
    property_asset_id: int | None = None
    objective: str | None = None
    horizon: str | None = None
    target_value_uf: Decimal | None = None
    urgency: str | None = None
    risk_profile: str | None = None
    next_move: str | None = None
    desired_property_type: str | None = None
    desired_communes: list[str] | None = None
    desired_budget_uf: Decimal | None = None


class PatrimonyService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_property(
        self,
        *,
        user_id: int,
        payload: PropertyAssetInput,
        valuation: PropertyValuationSnapshotInput | None = None,
    ) -> PropertyAssetORM:
        asset = PropertyAssetORM(
            user_id=user_id,
            name=payload.name.strip(),
            comuna=payload.comuna.strip().lower(),
            property_type=(payload.property_type or "unknown").strip().lower(),
            m2=payload.m2,
            built_area_m2=payload.built_area_m2,
            land_area_m2=payload.land_area_m2,
            usable_area_m2=payload.usable_area_m2,
            bedrooms=payload.bedrooms,
            bathrooms=payload.bathrooms,
            parking=payload.parking,
            lat=payload.lat,
            lon=payload.lon,
            characteristics=payload.characteristics or {},
        )
        self._session.add(asset)
        if valuation is not None:
            asset.valuation_snapshots.append(_snapshot_from_input(valuation))
        await self._session.commit()
        await self._session.refresh(asset, attribute_names=["valuation_snapshots"])
        return asset

    async def list_properties(self, *, user_id: int) -> list[PropertyAssetORM]:
        stmt = (
            select(PropertyAssetORM)
            .options(selectinload(PropertyAssetORM.valuation_snapshots))
            .where(PropertyAssetORM.user_id == user_id)
            .order_by(PropertyAssetORM.updated_at.desc(), PropertyAssetORM.id.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_property(self, *, user_id: int, property_id: int) -> PropertyAssetORM:
        stmt = (
            select(PropertyAssetORM)
            .options(selectinload(PropertyAssetORM.valuation_snapshots))
            .where(PropertyAssetORM.id == property_id)
            .where(PropertyAssetORM.user_id == user_id)
        )
        asset = (await self._session.execute(stmt)).scalar_one_or_none()
        if asset is None:
            raise PatrimonyError("Propiedad no encontrada", status_code=404)
        return asset

    async def update_property(
        self,
        *,
        user_id: int,
        property_id: int,
        payload: PropertyAssetInput | None = None,
        valuation: PropertyValuationSnapshotInput | None = None,
    ) -> PropertyAssetORM:
        asset = await self.get_property(user_id=user_id, property_id=property_id)
        if payload is not None:
            asset.name = payload.name.strip()
            asset.comuna = payload.comuna.strip().lower()
            asset.property_type = (payload.property_type or "unknown").strip().lower()
            asset.m2 = payload.m2
            asset.built_area_m2 = payload.built_area_m2
            asset.land_area_m2 = payload.land_area_m2
            asset.usable_area_m2 = payload.usable_area_m2
            asset.bedrooms = payload.bedrooms
            asset.bathrooms = payload.bathrooms
            asset.parking = payload.parking
            asset.lat = payload.lat
            asset.lon = payload.lon
            asset.characteristics = payload.characteristics or {}
        if valuation is not None:
            asset.valuation_snapshots.append(_snapshot_from_input(valuation))
        await self._session.commit()
        await self._session.refresh(asset, attribute_names=["valuation_snapshots"])
        return asset

    async def delete_property(self, *, user_id: int, property_id: int) -> None:
        asset = await self.get_property(user_id=user_id, property_id=property_id)
        await self._session.delete(asset)
        await self._session.commit()

    async def create_strategy(self, *, user_id: int, payload: PatrimonyStrategyInput) -> PatrimonyStrategyORM:
        await self.get_property(user_id=user_id, property_id=payload.property_asset_id)
        strategy = PatrimonyStrategyORM(
            user_id=user_id,
            property_asset_id=payload.property_asset_id,
            objective=payload.objective.strip(),
            horizon=_clean_text(payload.horizon),
            target_value_uf=payload.target_value_uf,
            urgency=_clean_text(payload.urgency),
            risk_profile=_clean_text(payload.risk_profile),
            next_move=_clean_text(payload.next_move),
            desired_property_type=_clean_text(payload.desired_property_type),
            desired_communes=_clean_list(payload.desired_communes),
            desired_budget_uf=payload.desired_budget_uf,
        )
        self._session.add(strategy)
        await self._session.commit()
        return await self.get_strategy(user_id=user_id, strategy_id=strategy.id)

    async def list_strategies(self, *, user_id: int) -> list[PatrimonyStrategyORM]:
        stmt = (
            select(PatrimonyStrategyORM)
            .options(selectinload(PatrimonyStrategyORM.property).selectinload(PropertyAssetORM.valuation_snapshots))
            .where(PatrimonyStrategyORM.user_id == user_id)
            .order_by(PatrimonyStrategyORM.updated_at.desc(), PatrimonyStrategyORM.id.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_strategy(self, *, user_id: int, strategy_id: int) -> PatrimonyStrategyORM:
        stmt = (
            select(PatrimonyStrategyORM)
            .options(selectinload(PatrimonyStrategyORM.property).selectinload(PropertyAssetORM.valuation_snapshots))
            .where(PatrimonyStrategyORM.id == strategy_id)
            .where(PatrimonyStrategyORM.user_id == user_id)
        )
        strategy = (await self._session.execute(stmt)).scalar_one_or_none()
        if strategy is None:
            raise PatrimonyError("Estrategia no encontrada", status_code=404)
        return strategy

    async def update_strategy(
        self,
        *,
        user_id: int,
        strategy_id: int,
        payload: PatrimonyStrategyPatchInput,
    ) -> PatrimonyStrategyORM:
        strategy = await self.get_strategy(user_id=user_id, strategy_id=strategy_id)
        if "property_asset_id" in payload.fields and payload.property_asset_id is not None:
            await self.get_property(user_id=user_id, property_id=payload.property_asset_id)
            strategy.property_asset_id = payload.property_asset_id
        if "objective" in payload.fields and payload.objective is not None:
            strategy.objective = payload.objective.strip()
        if "horizon" in payload.fields:
            strategy.horizon = _clean_text(payload.horizon)
        if "target_value_uf" in payload.fields:
            strategy.target_value_uf = payload.target_value_uf
        if "urgency" in payload.fields:
            strategy.urgency = _clean_text(payload.urgency)
        if "risk_profile" in payload.fields:
            strategy.risk_profile = _clean_text(payload.risk_profile)
        if "next_move" in payload.fields:
            strategy.next_move = _clean_text(payload.next_move)
        if "desired_property_type" in payload.fields:
            strategy.desired_property_type = _clean_text(payload.desired_property_type)
        if "desired_communes" in payload.fields:
            strategy.desired_communes = _clean_list(payload.desired_communes)
        if "desired_budget_uf" in payload.fields:
            strategy.desired_budget_uf = payload.desired_budget_uf
        await self._session.commit()
        await self._session.refresh(strategy, attribute_names=["property"])
        return await self.get_strategy(user_id=user_id, strategy_id=strategy.id)

    async def delete_strategy(self, *, user_id: int, strategy_id: int) -> None:
        strategy = await self.get_strategy(user_id=user_id, strategy_id=strategy_id)
        await self._session.delete(strategy)
        await self._session.commit()

    async def list_developments(self) -> list[TerritorialDevelopmentORM]:
        stmt = (
            select(TerritorialDevelopmentORM)
            .where(TerritorialDevelopmentORM.is_active.is_(True))
            .order_by(TerritorialDevelopmentORM.source_date.desc(), TerritorialDevelopmentORM.id.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_property_developments(
        self,
        *,
        user_id: int,
        property_id: int,
    ) -> list[TerritorialDevelopmentORM]:
        asset = await self.get_property(user_id=user_id, property_id=property_id)
        developments = await self.list_developments()
        return [development for development in developments if _matches_development(asset, development)]


def _snapshot_from_input(payload: PropertyValuationSnapshotInput) -> PropertyValuationSnapshotORM:
    return PropertyValuationSnapshotORM(
        estimated_value_uf=payload.estimated_value_uf,
        estimated_value_clp=payload.estimated_value_clp,
        lower_bound_uf=payload.lower_bound_uf,
        upper_bound_uf=payload.upper_bound_uf,
        lower_bound_clp=payload.lower_bound_clp,
        upper_bound_clp=payload.upper_bound_clp,
        confidence=payload.confidence,
        confidence_score=payload.confidence_score,
        engine_name=payload.engine_name,
        engine_version=payload.engine_version,
        engine_payload=payload.engine_payload or {},
        snapshot_at=payload.snapshot_at or datetime.now(UTC),
    )


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return [cleaned for value in values if (cleaned := value.strip().lower())]


def _matches_development(asset: PropertyAssetORM, development: TerritorialDevelopmentORM) -> bool:
    comuna = _normalize_key(asset.comuna)
    communes = {_normalize_key(value) for value in development.affected_communes or []}
    if comuna in communes:
        return True
    property_microzone = _normalize_key(str(asset.characteristics.get("microzone") or ""))
    if not property_microzone:
        return False
    microzones = {_normalize_key(value) for value in development.affected_microzones or []}
    return property_microzone in microzones


def _normalize_key(value: str) -> str:
    return " ".join(value.replace("_", " ").strip().lower().split())
