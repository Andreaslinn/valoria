"""Authenticated patrimony endpoints for owned homes."""
from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from api.deps import AppSettings, CurrentUser, DbSession, PatrimonyServiceDep
from infrastructure.db.models import (
    PatrimonyAlertORM,
    PatrimonyStrategyORM,
    PropertyAssetORM,
    PropertyValuationSnapshotORM,
    TerritorialDevelopmentORM,
)
from services.market_intelligence import MarketIntelligenceConfig, build_communes_summary
from services.patrimony import (
    PatrimonyError,
    PatrimonyStrategyInput,
    PatrimonyStrategyPatchInput,
    PropertyAssetInput,
    PropertyValuationSnapshotInput,
)
from services.patrimony_alerts import PatrimonyAlertService

router = APIRouter(prefix="/patrimony", tags=["patrimony"])


class PropertyValuationSnapshotIn(BaseModel):
    estimated_value_uf: Decimal | None = Field(default=None, gt=0)
    estimated_value_clp: Decimal | None = Field(default=None, gt=0)
    lower_bound_uf: Decimal | None = Field(default=None, gt=0)
    upper_bound_uf: Decimal | None = Field(default=None, gt=0)
    lower_bound_clp: Decimal | None = Field(default=None, gt=0)
    upper_bound_clp: Decimal | None = Field(default=None, gt=0)
    confidence: str | None = Field(default=None, max_length=32)
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    engine_name: str | None = Field(default=None, max_length=64)
    engine_version: str | None = Field(default=None, max_length=64)
    engine_payload: dict[str, Any] = Field(default_factory=dict)
    snapshot_at: datetime | None = None


class PropertyAssetIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    comuna: str = Field(min_length=1, max_length=64)
    property_type: str | None = Field(default=None, max_length=32)
    m2: float = Field(gt=0)
    built_area_m2: float | None = Field(default=None, gt=0)
    land_area_m2: float | None = Field(default=None, gt=0)
    usable_area_m2: float | None = Field(default=None, gt=0)
    bedrooms: int | None = Field(default=None, ge=0)
    bathrooms: int | None = Field(default=None, ge=0)
    parking: int | None = Field(default=None, ge=0)
    lat: float | None = None
    lon: float | None = None
    characteristics: dict[str, Any] = Field(default_factory=dict)
    valuation: PropertyValuationSnapshotIn | None = None


class PropertyAssetPatchIn(BaseModel):
    property: PropertyAssetIn | None = None
    valuation: PropertyValuationSnapshotIn | None = None


class PropertyValuationSnapshotOut(BaseModel):
    id: int
    estimated_value_uf: float | None
    estimated_value_clp: float | None
    lower_bound_uf: float | None
    upper_bound_uf: float | None
    lower_bound_clp: float | None
    upper_bound_clp: float | None
    confidence: str | None
    confidence_score: float | None
    engine_name: str | None
    engine_version: str | None
    engine_payload: dict[str, Any]
    snapshot_at: datetime
    created_at: datetime


class PropertyAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    comuna: str
    property_type: str
    m2: float
    built_area_m2: float | None
    land_area_m2: float | None
    usable_area_m2: float | None
    bedrooms: int | None
    bathrooms: int | None
    parking: int | None
    lat: float | None
    lon: float | None
    characteristics: dict[str, Any]
    latest_valuation: PropertyValuationSnapshotOut | None
    valuation_snapshots: list[PropertyValuationSnapshotOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PropertyAssetListOut(BaseModel):
    items: list[PropertyAssetOut] = Field(default_factory=list)


class PropertyDeleteOut(BaseModel):
    id: int
    deleted: bool


StrategyObjective = Literal[
    "maintain",
    "sell",
    "sell_and_buy",
    "buy_to_invest",
    "grow_patrimony",
]


class PatrimonyStrategyIn(BaseModel):
    property_asset_id: int = Field(gt=0)
    objective: StrategyObjective
    horizon: str | None = Field(default=None, max_length=64)
    target_value_uf: Decimal | None = Field(default=None, gt=0)
    urgency: str | None = Field(default=None, max_length=32)
    risk_profile: str | None = Field(default=None, max_length=32)
    next_move: str | None = Field(default=None, max_length=1000)
    desired_property_type: str | None = Field(default=None, max_length=32)
    desired_communes: list[str] = Field(default_factory=list, max_length=12)
    desired_budget_uf: Decimal | None = Field(default=None, gt=0)


class PatrimonyStrategyPatchIn(BaseModel):
    property_asset_id: int | None = Field(default=None, gt=0)
    objective: StrategyObjective | None = None
    horizon: str | None = Field(default=None, max_length=64)
    target_value_uf: Decimal | None = Field(default=None, gt=0)
    urgency: str | None = Field(default=None, max_length=32)
    risk_profile: str | None = Field(default=None, max_length=32)
    next_move: str | None = Field(default=None, max_length=1000)
    desired_property_type: str | None = Field(default=None, max_length=32)
    desired_communes: list[str] | None = Field(default=None, max_length=12)
    desired_budget_uf: Decimal | None = Field(default=None, gt=0)


class StrategyRecommendationOut(BaseModel):
    status: str
    current_recommendation: str | None = None
    progress_to_target_pct: float | None = None
    latest_valuation_uf: float | None = None
    target_value_uf: float | None = None
    next_steps: list[str] = Field(default_factory=list)
    action_conditions: list[str] = Field(default_factory=list)
    suggested_next_review: str | None = None
    reasons: list[str] = Field(default_factory=list)


class PatrimonyStrategyOut(BaseModel):
    id: int
    user_id: int
    property_asset_id: int
    objective: StrategyObjective
    horizon: str | None
    target_value_uf: float | None
    urgency: str | None
    risk_profile: str | None
    next_move: str | None
    desired_property_type: str | None
    desired_communes: list[str] = Field(default_factory=list)
    desired_budget_uf: float | None
    recommendation: StrategyRecommendationOut
    created_at: datetime
    updated_at: datetime


class PatrimonyStrategyListOut(BaseModel):
    items: list[PatrimonyStrategyOut] = Field(default_factory=list)


class PatrimonyStrategyDeleteOut(BaseModel):
    id: int
    deleted: bool


DevelopmentStatus = Literal[
    "announced",
    "planned",
    "confirmed",
    "under_construction",
    "completed",
    "cancelled",
]


class TerritorialScenarioOut(BaseModel):
    conservative_min_pct: float | None = None
    conservative_max_pct: float | None = None
    central_min_pct: float | None = None
    central_max_pct: float | None = None
    favorable_max_pct: float | None = None
    narrative: str


class TerritorialSourceOut(BaseModel):
    name: str
    url: str | None = None
    date: date_cls | None = None


class TerritorialDevelopmentOut(BaseModel):
    id: int
    name: str
    development_type: str
    status: DevelopmentStatus
    description: str
    affected_communes: list[str] = Field(default_factory=list)
    affected_microzones: list[str] = Field(default_factory=list)
    expected_start_date: date_cls | None = None
    expected_completion_date: date_cls | None = None
    horizon: str
    source: TerritorialSourceOut
    confidence: str
    methodology: str
    risks: list[str] = Field(default_factory=list)
    scenarios: TerritorialScenarioOut
    is_active: bool


class TerritorialDevelopmentListOut(BaseModel):
    items: list[TerritorialDevelopmentOut] = Field(default_factory=list)


class PatrimonyAlertOut(BaseModel):
    id: int
    user_id: int
    property_asset_id: int | None = None
    strategy_id: int | None = None
    territorial_development_id: int | None = None
    alert_type: str
    title: str
    message: str
    severity: str
    metadata: dict[str, Any]
    created_at: datetime
    read_at: datetime | None = None
    dismissed_at: datetime | None = None
    property_name: str | None = None
    strategy_objective: str | None = None
    territorial_development_name: str | None = None


class PatrimonyAlertListOut(BaseModel):
    items: list[PatrimonyAlertOut] = Field(default_factory=list)


class PatrimonyAlertEvaluationOut(BaseModel):
    created: int
    existing: int


PatrimonyRecommendation = Literal[
    "maintain",
    "monitor",
    "prepare_sale",
    "evaluate_exit",
    "favorable_market",
]


class PatrimonyIntelligenceOut(BaseModel):
    status: str
    property_id: int
    comuna: str
    buyer_seller_balance: str | None = None
    dynamism: str | None = None
    observed_publication_time_days: int | None = None
    recent_movement: str | None = None
    recommendation: PatrimonyRecommendation | None = None
    reasons: list[str] = Field(default_factory=list)
    change_conditions: list[str] = Field(default_factory=list)
    confidence: str
    updated_at: datetime | None = None
    signals: dict[str, Any] = Field(default_factory=dict)
    territorial_developments: list[TerritorialDevelopmentOut] = Field(default_factory=list)
    territorial_projection_message: str = "No hay proyecciones territoriales verificadas disponibles para esta propiedad."


@router.post("/properties", response_model=PropertyAssetOut, status_code=status.HTTP_201_CREATED)
async def create_property(
    payload: PropertyAssetIn,
    current_user: CurrentUser,
    service: PatrimonyServiceDep,
    session: DbSession,
) -> PropertyAssetOut:
    assert current_user.id is not None
    asset = await service.create_property(
        user_id=current_user.id,
        payload=_asset_input(payload),
        valuation=_snapshot_input(payload.valuation),
    )
    await PatrimonyAlertService(session).evaluate_user(user_id=current_user.id)
    return _asset_out(asset)


@router.get("/properties", response_model=PropertyAssetListOut)
async def list_properties(
    current_user: CurrentUser,
    service: PatrimonyServiceDep,
) -> PropertyAssetListOut:
    assert current_user.id is not None
    items = await service.list_properties(user_id=current_user.id)
    return PropertyAssetListOut(items=[_asset_out(item) for item in items])


@router.get("/properties/{property_id}", response_model=PropertyAssetOut)
async def get_property(
    property_id: int,
    current_user: CurrentUser,
    service: PatrimonyServiceDep,
) -> PropertyAssetOut:
    assert current_user.id is not None
    try:
        return _asset_out(await service.get_property(user_id=current_user.id, property_id=property_id))
    except PatrimonyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.patch("/properties/{property_id}", response_model=PropertyAssetOut)
async def update_property(
    property_id: int,
    payload: PropertyAssetPatchIn,
    current_user: CurrentUser,
    service: PatrimonyServiceDep,
    session: DbSession,
) -> PropertyAssetOut:
    assert current_user.id is not None
    try:
        asset = await service.update_property(
            user_id=current_user.id,
            property_id=property_id,
            payload=_asset_input(payload.property) if payload.property else None,
            valuation=_snapshot_input(payload.valuation),
        )
        if payload.valuation is not None:
            await PatrimonyAlertService(session).evaluate_user(user_id=current_user.id)
        return _asset_out(asset)
    except PatrimonyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/properties/{property_id}/intelligence", response_model=PatrimonyIntelligenceOut)
async def get_property_intelligence(
    property_id: int,
    current_user: CurrentUser,
    service: PatrimonyServiceDep,
    session: DbSession,
    settings: AppSettings,
) -> PatrimonyIntelligenceOut:
    assert current_user.id is not None
    try:
        asset = await service.get_property(user_id=current_user.id, property_id=property_id)
    except PatrimonyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    summary = await build_communes_summary(
        session,
        config=MarketIntelligenceConfig(
            commune_min_active_listings=settings.market_commune_min_active_listings,
            commune_min_time_sample=settings.market_commune_min_time_sample,
            commune_min_price_history_sample=settings.market_commune_min_price_history_sample,
        ),
    )
    developments = await service.list_property_developments(user_id=current_user.id, property_id=property_id)
    await PatrimonyAlertService(session).evaluate_user(user_id=current_user.id)
    return _property_intelligence_out(asset, summary, developments=developments)


@router.get("/developments", response_model=TerritorialDevelopmentListOut)
async def list_developments(
    _current_user: CurrentUser,
    service: PatrimonyServiceDep,
) -> TerritorialDevelopmentListOut:
    return TerritorialDevelopmentListOut(items=[_development_out(item) for item in await service.list_developments()])


@router.get("/properties/{property_id}/developments", response_model=TerritorialDevelopmentListOut)
async def list_property_developments(
    property_id: int,
    current_user: CurrentUser,
    service: PatrimonyServiceDep,
) -> TerritorialDevelopmentListOut:
    assert current_user.id is not None
    try:
        items = await service.list_property_developments(user_id=current_user.id, property_id=property_id)
    except PatrimonyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return TerritorialDevelopmentListOut(items=[_development_out(item) for item in items])


@router.post("/strategies", response_model=PatrimonyStrategyOut, status_code=status.HTTP_201_CREATED)
async def create_strategy(
    payload: PatrimonyStrategyIn,
    current_user: CurrentUser,
    service: PatrimonyServiceDep,
    session: DbSession,
    settings: AppSettings,
) -> PatrimonyStrategyOut:
    assert current_user.id is not None
    try:
        strategy = await service.create_strategy(user_id=current_user.id, payload=_strategy_input(payload))
    except PatrimonyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    summary = await _communes_summary(session, settings)
    return _strategy_out(strategy, summary)


@router.get("/strategies", response_model=PatrimonyStrategyListOut)
async def list_strategies(
    current_user: CurrentUser,
    service: PatrimonyServiceDep,
    session: DbSession,
    settings: AppSettings,
) -> PatrimonyStrategyListOut:
    assert current_user.id is not None
    strategies = await service.list_strategies(user_id=current_user.id)
    summary = await _communes_summary(session, settings)
    return PatrimonyStrategyListOut(items=[_strategy_out(strategy, summary) for strategy in strategies])


@router.get("/strategies/{strategy_id}", response_model=PatrimonyStrategyOut)
async def get_strategy(
    strategy_id: int,
    current_user: CurrentUser,
    service: PatrimonyServiceDep,
    session: DbSession,
    settings: AppSettings,
) -> PatrimonyStrategyOut:
    assert current_user.id is not None
    try:
        strategy = await service.get_strategy(user_id=current_user.id, strategy_id=strategy_id)
    except PatrimonyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    summary = await _communes_summary(session, settings)
    return _strategy_out(strategy, summary)


@router.patch("/strategies/{strategy_id}", response_model=PatrimonyStrategyOut)
async def update_strategy(
    strategy_id: int,
    payload: PatrimonyStrategyPatchIn,
    current_user: CurrentUser,
    service: PatrimonyServiceDep,
    session: DbSession,
    settings: AppSettings,
) -> PatrimonyStrategyOut:
    assert current_user.id is not None
    try:
        strategy = await service.update_strategy(
            user_id=current_user.id,
            strategy_id=strategy_id,
            payload=_strategy_patch_input(payload),
        )
    except PatrimonyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    summary = await _communes_summary(session, settings)
    return _strategy_out(strategy, summary)


@router.delete("/strategies/{strategy_id}", response_model=PatrimonyStrategyDeleteOut)
async def delete_strategy(
    strategy_id: int,
    current_user: CurrentUser,
    service: PatrimonyServiceDep,
) -> PatrimonyStrategyDeleteOut:
    assert current_user.id is not None
    try:
        await service.delete_strategy(user_id=current_user.id, strategy_id=strategy_id)
    except PatrimonyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return PatrimonyStrategyDeleteOut(id=strategy_id, deleted=True)


@router.get("/alerts", response_model=PatrimonyAlertListOut)
async def list_patrimony_alerts(
    current_user: CurrentUser,
    session: DbSession,
    include_read: bool = False,
    include_dismissed: bool = False,
) -> PatrimonyAlertListOut:
    assert current_user.id is not None
    alerts = await PatrimonyAlertService(session).list_alerts(user_id=current_user.id, unread_only=not include_read, include_dismissed=include_dismissed)
    return PatrimonyAlertListOut(items=[_patrimony_alert_out(alert) for alert in alerts])


@router.patch("/alerts/{alert_id}/read", response_model=PatrimonyAlertOut)
async def mark_patrimony_alert_read(
    alert_id: int,
    current_user: CurrentUser,
    session: DbSession,
) -> PatrimonyAlertOut:
    assert current_user.id is not None
    try:
        alert = await PatrimonyAlertService(session).mark_read(user_id=current_user.id, alert_id=alert_id)
    except PatrimonyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _patrimony_alert_out(alert)


@router.patch("/alerts/{alert_id}/dismiss", response_model=PatrimonyAlertOut)
async def dismiss_patrimony_alert(
    alert_id: int,
    current_user: CurrentUser,
    session: DbSession,
) -> PatrimonyAlertOut:
    assert current_user.id is not None
    try:
        alert = await PatrimonyAlertService(session).dismiss(user_id=current_user.id, alert_id=alert_id)
    except PatrimonyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _patrimony_alert_out(alert)


@router.post("/alerts/evaluate", response_model=PatrimonyAlertEvaluationOut)
async def evaluate_patrimony_alerts(
    current_user: CurrentUser,
    session: DbSession,
) -> PatrimonyAlertEvaluationOut:
    assert current_user.id is not None
    result = await PatrimonyAlertService(session).evaluate_user(user_id=current_user.id)
    return PatrimonyAlertEvaluationOut(created=result.created, existing=result.existing)


@router.delete("/properties/{property_id}", response_model=PropertyDeleteOut)
async def delete_property(
    property_id: int,
    current_user: CurrentUser,
    service: PatrimonyServiceDep,
) -> PropertyDeleteOut:
    assert current_user.id is not None
    try:
        await service.delete_property(user_id=current_user.id, property_id=property_id)
    except PatrimonyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return PropertyDeleteOut(id=property_id, deleted=True)


def _asset_input(payload: PropertyAssetIn) -> PropertyAssetInput:
    return PropertyAssetInput(
        name=payload.name,
        comuna=payload.comuna,
        property_type=payload.property_type,
        m2=payload.m2,
        built_area_m2=payload.built_area_m2,
        land_area_m2=payload.land_area_m2,
        usable_area_m2=payload.usable_area_m2,
        bedrooms=payload.bedrooms,
        bathrooms=payload.bathrooms,
        parking=payload.parking,
        lat=payload.lat,
        lon=payload.lon,
        characteristics=payload.characteristics,
    )


def _snapshot_input(payload: PropertyValuationSnapshotIn | None) -> PropertyValuationSnapshotInput | None:
    if payload is None:
        return None
    return PropertyValuationSnapshotInput(
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
        engine_payload=payload.engine_payload,
        snapshot_at=payload.snapshot_at,
    )


def _strategy_input(payload: PatrimonyStrategyIn) -> PatrimonyStrategyInput:
    return PatrimonyStrategyInput(
        property_asset_id=payload.property_asset_id,
        objective=payload.objective,
        horizon=payload.horizon,
        target_value_uf=payload.target_value_uf,
        urgency=payload.urgency,
        risk_profile=payload.risk_profile,
        next_move=payload.next_move,
        desired_property_type=payload.desired_property_type,
        desired_communes=payload.desired_communes,
        desired_budget_uf=payload.desired_budget_uf,
    )


def _strategy_patch_input(payload: PatrimonyStrategyPatchIn) -> PatrimonyStrategyPatchInput:
    fields = payload.model_fields_set
    return PatrimonyStrategyPatchInput(
        fields=set(fields),
        property_asset_id=payload.property_asset_id if "property_asset_id" in fields else None,
        objective=payload.objective if "objective" in fields else None,
        horizon=payload.horizon if "horizon" in fields else None,
        target_value_uf=payload.target_value_uf if "target_value_uf" in fields else None,
        urgency=payload.urgency if "urgency" in fields else None,
        risk_profile=payload.risk_profile if "risk_profile" in fields else None,
        next_move=payload.next_move if "next_move" in fields else None,
        desired_property_type=payload.desired_property_type if "desired_property_type" in fields else None,
        desired_communes=payload.desired_communes if "desired_communes" in fields else None,
        desired_budget_uf=payload.desired_budget_uf if "desired_budget_uf" in fields else None,
    )


def _asset_out(asset: PropertyAssetORM) -> PropertyAssetOut:
    snapshots = sorted(asset.valuation_snapshots, key=lambda item: (item.snapshot_at, item.id or 0))
    latest = snapshots[-1] if snapshots else None
    return PropertyAssetOut(
        id=asset.id,
        user_id=asset.user_id,
        name=asset.name,
        comuna=asset.comuna,
        property_type=asset.property_type,
        m2=asset.m2,
        built_area_m2=asset.built_area_m2,
        land_area_m2=asset.land_area_m2,
        usable_area_m2=asset.usable_area_m2,
        bedrooms=asset.bedrooms,
        bathrooms=asset.bathrooms,
        parking=asset.parking,
        lat=asset.lat,
        lon=asset.lon,
        characteristics=asset.characteristics,
        latest_valuation=_snapshot_out(latest) if latest else None,
        valuation_snapshots=[_snapshot_out(snapshot) for snapshot in snapshots],
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


def _strategy_out(strategy: PatrimonyStrategyORM, summary: dict[str, Any]) -> PatrimonyStrategyOut:
    return PatrimonyStrategyOut(
        id=strategy.id,
        user_id=strategy.user_id,
        property_asset_id=strategy.property_asset_id,
        objective=strategy.objective,
        horizon=strategy.horizon,
        target_value_uf=_float(strategy.target_value_uf),
        urgency=strategy.urgency,
        risk_profile=strategy.risk_profile,
        next_move=strategy.next_move,
        desired_property_type=strategy.desired_property_type,
        desired_communes=list(strategy.desired_communes or []),
        desired_budget_uf=_float(strategy.desired_budget_uf),
        recommendation=_strategy_recommendation_out(strategy, summary),
        created_at=strategy.created_at,
        updated_at=strategy.updated_at,
    )


def _patrimony_alert_out(alert: PatrimonyAlertORM) -> PatrimonyAlertOut:
    return PatrimonyAlertOut(
        id=alert.id,
        user_id=alert.user_id,
        property_asset_id=alert.property_asset_id,
        strategy_id=alert.strategy_id,
        territorial_development_id=alert.territorial_development_id,
        alert_type=alert.alert_type,
        title=alert.title,
        message=alert.message,
        severity=alert.severity,
        metadata=alert.metadata_,
        created_at=alert.created_at,
        read_at=alert.read_at,
        dismissed_at=alert.dismissed_at,
        property_name=alert.property.name if alert.property else None,
        strategy_objective=alert.strategy.objective if alert.strategy else None,
        territorial_development_name=alert.territorial_development.name if alert.territorial_development else None,
    )


def _strategy_recommendation_out(strategy: PatrimonyStrategyORM, summary: dict[str, Any]) -> StrategyRecommendationOut:
    latest = _latest_snapshot(strategy.property)
    latest_uf = _float(latest.estimated_value_uf) if latest else None
    target_uf = _float(strategy.target_value_uf)
    intelligence = _property_intelligence_out(strategy.property, summary)
    progress = _progress_to_target(latest_uf, target_uf)
    if intelligence.status != "available":
        return StrategyRecommendationOut(
            status="insufficient_data",
            current_recommendation="Aun no hay suficiente informacion para una recomendacion",
            progress_to_target_pct=progress,
            latest_valuation_uf=latest_uf,
            target_value_uf=target_uf,
            next_steps=_strategy_next_steps(strategy, intelligence, latest_uf, target_uf),
            action_conditions=["Esperar una muestra suficiente de mercado para la comuna antes de tomar decisiones patrimoniales."],
            suggested_next_review=_review_window(strategy),
            reasons=["No hay senales de mercado suficientes para explicar una recomendacion."],
        )
    current = _strategy_recommendation_label(strategy, intelligence)
    return StrategyRecommendationOut(
        status="available",
        current_recommendation=current,
        progress_to_target_pct=progress,
        latest_valuation_uf=latest_uf,
        target_value_uf=target_uf,
        next_steps=_strategy_next_steps(strategy, intelligence, latest_uf, target_uf),
        action_conditions=_strategy_action_conditions(strategy, intelligence),
        suggested_next_review=_review_window(strategy),
        reasons=_strategy_reasons(strategy, intelligence, progress),
    )


def _latest_snapshot(asset: PropertyAssetORM) -> PropertyValuationSnapshotORM | None:
    snapshots = sorted(asset.valuation_snapshots, key=lambda item: (item.snapshot_at, item.id or 0))
    return snapshots[-1] if snapshots else None


def _progress_to_target(latest_uf: float | None, target_uf: float | None) -> float | None:
    if latest_uf is None or target_uf is None or target_uf <= 0:
        return None
    return round((latest_uf / target_uf) * 100, 1)


def _strategy_recommendation_label(strategy: PatrimonyStrategyORM, intelligence: PatrimonyIntelligenceOut) -> str:
    objective = strategy.objective
    patrimony_signal = intelligence.recommendation
    if objective == "maintain":
        return "Mantener y revisar senales de mercado"
    if objective == "sell" and patrimony_signal in {"prepare_sale", "favorable_market"}:
        return "Preparar venta con validacion de precio objetivo"
    if objective == "sell":
        return "Monitorear antes de activar venta"
    if objective == "sell_and_buy":
        return "Preparar venta y explorar compra con cautela"
    if objective == "buy_to_invest":
        return "Explorar oportunidades de inversion sin duplicar radar"
    return "Ordenar prioridades para crecer patrimonio"


def _strategy_next_steps(
    strategy: PatrimonyStrategyORM,
    intelligence: PatrimonyIntelligenceOut,
    latest_uf: float | None,
    target_uf: float | None,
) -> list[str]:
    steps = ["Revisar la ultima tasacion guardada y confirmar que refleja el estado actual de la propiedad."]
    if target_uf is not None and latest_uf is not None:
        steps.append("Comparar el valor estimado con el precio objetivo antes de decidir una accion.")
    if strategy.next_move:
        steps.append(strategy.next_move)
    if strategy.objective in {"sell_and_buy", "buy_to_invest", "grow_patrimony"}:
        steps.append("Usar Radar como exploracion separada para oportunidades de compra.")
    if intelligence.recommendation in {"prepare_sale", "favorable_market"}:
        steps.append("Preparar documentacion y criterios de precio sin asumir un momento exacto de venta.")
    return steps


def _strategy_action_conditions(strategy: PatrimonyStrategyORM, intelligence: PatrimonyIntelligenceOut) -> list[str]:
    conditions = list(intelligence.change_conditions[:3])
    if strategy.target_value_uf is not None:
        conditions.append("Actuar solo si la tasacion actual se acerca al precio objetivo definido.")
    if strategy.urgency == "high":
        conditions.append("Si la urgencia se mantiene alta, priorizar liquidez y certeza sobre esperar una mejora marginal.")
    return conditions


def _strategy_reasons(
    strategy: PatrimonyStrategyORM,
    intelligence: PatrimonyIntelligenceOut,
    progress: float | None,
) -> list[str]:
    reasons = [
        f"Objetivo declarado: {strategy.objective}.",
        f"Horizonte declarado: {strategy.horizon or 'no definido'}.",
        f"Senal patrimonial actual: {intelligence.recommendation or 'sin recomendacion'}.",
    ]
    if progress is not None:
        reasons.append(f"Progreso hacia precio objetivo: {progress}%.")
    if intelligence.buyer_seller_balance:
        reasons.append(f"Estado de mercado de la comuna: {intelligence.buyer_seller_balance}.")
    return reasons


def _review_window(strategy: PatrimonyStrategyORM) -> str:
    if strategy.urgency == "high":
        return "Revisar en 2 semanas"
    if strategy.horizon and "12" in strategy.horizon:
        return "Revisar en 60 dias"
    return "Revisar en 30 dias"


async def _communes_summary(session: DbSession, settings: AppSettings) -> dict[str, Any]:
    return await build_communes_summary(
        session,
        config=MarketIntelligenceConfig(
            commune_min_active_listings=settings.market_commune_min_active_listings,
            commune_min_time_sample=settings.market_commune_min_time_sample,
            commune_min_price_history_sample=settings.market_commune_min_price_history_sample,
        ),
    )


def _snapshot_out(snapshot: PropertyValuationSnapshotORM) -> PropertyValuationSnapshotOut:
    return PropertyValuationSnapshotOut(
        id=snapshot.id,
        estimated_value_uf=_float(snapshot.estimated_value_uf),
        estimated_value_clp=_float(snapshot.estimated_value_clp),
        lower_bound_uf=_float(snapshot.lower_bound_uf),
        upper_bound_uf=_float(snapshot.upper_bound_uf),
        lower_bound_clp=_float(snapshot.lower_bound_clp),
        upper_bound_clp=_float(snapshot.upper_bound_clp),
        confidence=snapshot.confidence,
        confidence_score=snapshot.confidence_score,
        engine_name=snapshot.engine_name,
        engine_version=snapshot.engine_version,
        engine_payload=snapshot.engine_payload,
        snapshot_at=snapshot.snapshot_at,
        created_at=snapshot.created_at,
    )


def _property_intelligence_out(
    asset: PropertyAssetORM,
    summary: dict[str, Any],
    *,
    developments: list[TerritorialDevelopmentORM] | None = None,
) -> PatrimonyIntelligenceOut:
    development_items = [_development_out(item) for item in developments or []]
    item = _commune_summary_item(summary, asset.comuna)
    if item is None:
        return PatrimonyIntelligenceOut(
            status="insufficient_data",
            property_id=asset.id,
            comuna=asset.comuna,
            confidence="low",
            reasons=[],
            change_conditions=[
                "Se requiere una muestra suficiente de publicaciones activas en la comuna.",
                "Se requiere historial observable de tiempo publicado y cambios de precio.",
            ],
            updated_at=summary.get("updated_at"),
            signals={"market_status": summary.get("status"), "minimum_sample": summary.get("minimum_sample", {})},
            territorial_developments=development_items,
            territorial_projection_message=_territorial_message(development_items),
        )

    recent_movement = _recent_movement(item)
    recommendation = _recommendation_for(item)
    reasons = _recommendation_reasons(item, recent_movement)
    conditions = _change_conditions(item)
    return PatrimonyIntelligenceOut(
        status="available",
        property_id=asset.id,
        comuna=asset.comuna,
        buyer_seller_balance=item.get("buyer_seller_balance") or item.get("market_balance_label"),
        dynamism=_dynamism_label(item),
        observed_publication_time_days=item.get("median_observed_days"),
        recent_movement=recent_movement,
        recommendation=recommendation,
        reasons=reasons,
        change_conditions=conditions,
        confidence=str(item.get("confidence") or "low"),
        updated_at=summary.get("updated_at"),
        signals={
            "active_listings": item.get("active_listings"),
            "new_7d": item.get("new_7d"),
            "removed_7d": item.get("removed_7d"),
            "net_flow_7d": item.get("net_flow_7d"),
            "price_drops_30d": item.get("price_drops_30d"),
            "price_drop_share_30d": item.get("price_drop_share_30d"),
            "observed_time_sample": item.get("observed_time_sample"),
            "price_history_sample": item.get("price_history_sample"),
            "market_balance_score": item.get("market_balance_score"),
        },
        territorial_developments=development_items,
        territorial_projection_message=_territorial_message(development_items),
    )


def _development_out(development: TerritorialDevelopmentORM) -> TerritorialDevelopmentOut:
    return TerritorialDevelopmentOut(
        id=development.id,
        name=development.name,
        development_type=development.development_type,
        status=development.status,
        description=development.description,
        affected_communes=list(development.affected_communes or []),
        affected_microzones=list(development.affected_microzones or []),
        expected_start_date=development.expected_start_date,
        expected_completion_date=development.expected_completion_date,
        horizon=_development_horizon(development),
        source=TerritorialSourceOut(
            name=development.source_name,
            url=development.source_url,
            date=development.source_date,
        ),
        confidence=development.confidence,
        methodology=development.methodology_note,
        risks=_development_risks(development),
        scenarios=TerritorialScenarioOut(
            conservative_min_pct=_float(development.conservative_min_pct),
            conservative_max_pct=_float(development.conservative_max_pct),
            central_min_pct=_float(development.central_min_pct),
            central_max_pct=_float(development.central_max_pct),
            favorable_max_pct=_float(development.favorable_max_pct),
            narrative=_scenario_narrative(development),
        ),
        is_active=development.is_active,
    )


def _development_horizon(development: TerritorialDevelopmentORM) -> str:
    start = development.expected_start_date.isoformat() if development.expected_start_date else "inicio no verificado"
    completion = (
        development.expected_completion_date.isoformat()
        if development.expected_completion_date
        else "termino no verificado"
    )
    return f"{start} a {completion}"


def _scenario_narrative(development: TerritorialDevelopmentORM) -> str:
    favorable = _float(development.favorable_max_pct)
    if favorable is None:
        return "No hay escenarios de impacto configurados para este proyecto territorial."
    return (
        "En el escenario favorable analizado, el impacto acumulado podria alcanzar "
        f"hasta {favorable:g} %, sujeto al avance efectivo del proyecto y a las condiciones del mercado."
    )


def _development_risks(development: TerritorialDevelopmentORM) -> list[str]:
    risks = [
        "Cambios de alcance, permisos, financiamiento o calendario podrian impedir el escenario.",
        "El mercado inmobiliario local podria absorber el impacto de forma distinta a la hipotesis metodologica.",
    ]
    if development.status in {"announced", "planned"}:
        risks.append("El proyecto aun no esta en etapa de ejecucion confirmada.")
    return risks


def _territorial_message(items: list[TerritorialDevelopmentOut]) -> str:
    if not items:
        return "No hay proyecciones territoriales verificadas disponibles para esta propiedad."
    return "Proyeccion por escenarios basada en proyectos territoriales respaldados y configurados."


def _commune_summary_item(summary: dict[str, Any], comuna: str) -> dict[str, Any] | None:
    target = _normalize_key(comuna)
    for item in summary.get("items", []):
        if _normalize_key(str(item.get("comuna") or "")) == target:
            return item
    return None


def _recommendation_for(item: dict[str, Any]) -> PatrimonyRecommendation:
    side = _market_side(item)
    confidence = str(item.get("confidence") or "low").lower()
    net_flow = int(item.get("net_flow_7d") or 0)
    price_drop_share = float(item.get("price_drop_share_30d") or 0)
    median_days = item.get("median_observed_days")

    if confidence == "low":
        return "monitor"
    if side == "seller" and net_flow <= 0 and price_drop_share < 0.08:
        return "favorable_market"
    if side == "seller":
        return "prepare_sale"
    if side == "buyer" and (price_drop_share >= 0.12 or (median_days is not None and median_days >= 75)):
        return "evaluate_exit"
    if side == "buyer":
        return "monitor"
    if _activity_score(item) <= 30:
        return "maintain"
    return "monitor"


def _recommendation_reasons(item: dict[str, Any], recent_movement: str) -> list[str]:
    reasons = [
        f"Balance comprador-vendedor: {item.get('buyer_seller_balance') or item.get('market_balance_label')}.",
        f"Movimiento reciente: {recent_movement}.",
    ]
    median_days = item.get("median_observed_days")
    if median_days is not None:
        reasons.append(f"Tiempo observado publicado mediano: {median_days} dias.")
    price_drops = int(item.get("price_drops_30d") or 0)
    if price_drops:
        reasons.append(f"{price_drops} publicaciones de la comuna registraron rebajas en 30 dias.")
    reasons.append(f"Muestra usada: {int(item.get('active_listings') or 0)} publicaciones activas.")
    return reasons


def _change_conditions(item: dict[str, Any]) -> list[str]:
    return [
        "Un aumento sostenido de nuevas publicaciones podria elevar la presion competitiva.",
        "Mas rebajas de precio en la comuna podrian debilitar la posicion vendedora.",
        "Una reduccion de oferta activa o retiros recientes podrian mejorar el balance para vender.",
        "Una muestra mas amplia de historial de precios y tiempo publicado podria cambiar la confianza.",
    ]


def _recent_movement(item: dict[str, Any]) -> str:
    net_flow = int(item.get("net_flow_7d") or 0)
    price_drops = int(item.get("price_drops_30d") or 0)
    if net_flow > 0 and price_drops > 0:
        return "Sube la oferta visible y hay rebajas recientes"
    if net_flow > 0:
        return "Sube la oferta visible"
    if net_flow < 0:
        return "Baja la oferta visible"
    if price_drops > 0:
        return "Oferta estable con rebajas recientes"
    return "Sin cambios relevantes en la oferta semanal"


def _dynamism_label(item: dict[str, Any]) -> str:
    score = _activity_score(item)
    if score >= 70:
        return "Actividad alta"
    if score >= 40:
        return "Actividad moderada"
    return "Actividad baja"


def _activity_score(item: dict[str, Any]) -> int:
    active = max(int(item.get("active_listings") or 0), 1)
    new_7d = int(item.get("new_7d") or 0)
    removed_7d = int(item.get("removed_7d") or 0)
    price_drops = int(item.get("price_drops_30d") or 0)
    return min(round(((new_7d + removed_7d) / active + (price_drops / active)) * 250), 100)


def _market_side(item: dict[str, Any]) -> str:
    label = str(item.get("buyer_seller_balance") or item.get("market_balance_label") or "").lower()
    if "comprador" in label:
        return "buyer"
    if "vendedor" in label:
        return "seller"
    return "balanced"


def _normalize_key(value: str) -> str:
    return " ".join(value.replace("_", " ").strip().lower().split())


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
