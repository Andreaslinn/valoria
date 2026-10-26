"""Honest Portfolio contracts for real data and future capabilities."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class PortfolioState(StrEnum):
    AVAILABLE = "available"
    NOT_AVAILABLE = "not_available"
    NEEDS_HISTORY = "needs_history"
    NEEDS_SNAPSHOT = "needs_snapshot"
    NEEDS_VALUATION = "needs_valuation"
    NEEDS_PRICE_HISTORY = "needs_price_history"
    NEEDS_USER_ACTION = "needs_user_action"
    INSUFFICIENT_DATA = "insufficient_data"
    DISABLED_FOR_BETA = "disabled_for_beta"


@dataclass(frozen=True)
class PortfolioCapabilityState:
    status: PortfolioState
    reason: str | None = None
    available: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "available": self.available,
        }


@dataclass(frozen=True)
class PortfolioItemAvmState(PortfolioCapabilityState):
    estimated_value_uf: Decimal | None = None
    estimated_value_clp: Decimal | None = None
    lower_bound_uf: Decimal | None = None
    upper_bound_uf: Decimal | None = None
    confidence: str | None = None
    snapshot_id: int | None = None
    snapshot_created_at: datetime | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = super().to_payload()
        payload.update(
            {
                "estimated_value_uf": _decimal_or_none(self.estimated_value_uf),
                "estimated_value_clp": _decimal_or_none(self.estimated_value_clp),
                "lower_bound_uf": _decimal_or_none(self.lower_bound_uf),
                "upper_bound_uf": _decimal_or_none(self.upper_bound_uf),
                "confidence": self.confidence,
                "snapshot_id": self.snapshot_id,
                "snapshot_created_at": _datetime_or_none(self.snapshot_created_at),
            }
        )
        return payload


@dataclass(frozen=True)
class PortfolioItemDeltaState(PortfolioCapabilityState):
    delta_uf: Decimal | None = None
    delta_pct: float | None = None
    snapshot_id: int | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = super().to_payload()
        payload.update(
            {
                "delta_uf": _decimal_or_none(self.delta_uf),
                "delta_pct": self.delta_pct,
                "snapshot_id": self.snapshot_id,
            }
        )
        return payload


@dataclass(frozen=True)
class PortfolioTrendState(PortfolioCapabilityState):
    direction: str | None = None
    points: tuple[Decimal, ...] = ()
    observation_window_days: int | None = None
    variation_pct: float | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = super().to_payload()
        payload.update(
            {
                "direction": self.direction,
                "points": [_decimal_or_none(point) for point in self.points],
                "observation_window_days": self.observation_window_days,
                "variation_pct": self.variation_pct,
            }
        )
        return payload


@dataclass(frozen=True)
class PortfolioUpsideState(PortfolioCapabilityState):
    total_upside_uf: Decimal | None = None
    average_delta_pct: float | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = super().to_payload()
        payload.update(
            {
                "total_upside_uf": _decimal_or_none(self.total_upside_uf),
                "average_delta_pct": self.average_delta_pct,
            }
        )
        return payload


@dataclass(frozen=True)
class PortfolioHistoryState(PortfolioCapabilityState):
    points: tuple[dict[str, Any], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload = super().to_payload()
        payload["points"] = [dict(point) for point in self.points]
        return payload


@dataclass(frozen=True)
class PortfolioComparedState(PortfolioCapabilityState):
    compared_listing_ids: tuple[int, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload = super().to_payload()
        payload["compared_listing_ids"] = list(self.compared_listing_ids)
        return payload


@dataclass(frozen=True)
class PortfolioFavoriteState(PortfolioCapabilityState):
    favorite_listing_ids: tuple[int, ...] = ()
    source: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = super().to_payload()
        payload.update(
            {
                "favorite_listing_ids": list(self.favorite_listing_ids),
                "source": self.source,
            }
        )
        return payload


@dataclass(frozen=True)
class PortfolioRecommendationState(PortfolioCapabilityState):
    recommendations: tuple[dict[str, Any], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload = super().to_payload()
        payload["recommendations"] = [dict(item) for item in self.recommendations]
        return payload


@dataclass(frozen=True)
class PortfolioItem:
    watchlist_item_id: int
    listing_id: int
    title: str
    comuna: str
    property_type: str
    m2: float | None
    bedrooms: int
    bathrooms: int
    parking: int
    published_price_clp: Decimal | None
    published_price_uf: Decimal | None
    price_basis: str
    price_data_quality: str
    url: str | None
    source: str
    listing_status: str
    saved_at: datetime
    avm: PortfolioItemAvmState
    delta: PortfolioItemDeltaState
    trend: PortfolioTrendState

    def to_payload(self) -> dict[str, Any]:
        return {
            "watchlist_item_id": self.watchlist_item_id,
            "listing_id": self.listing_id,
            "title": self.title,
            "comuna": self.comuna,
            "property_type": self.property_type,
            "m2": self.m2,
            "bedrooms": self.bedrooms,
            "bathrooms": self.bathrooms,
            "parking": self.parking,
            "published_price_clp": _decimal_or_none(self.published_price_clp),
            "published_price_uf": _decimal_or_none(self.published_price_uf),
            "price_basis": self.price_basis,
            "price_data_quality": self.price_data_quality,
            "url": self.url,
            "source": self.source,
            "listing_status": self.listing_status,
            "saved_at": _datetime_or_none(self.saved_at),
            "avm": self.avm.to_payload(),
            "delta": self.delta.to_payload(),
            "trend": self.trend.to_payload(),
        }


@dataclass(frozen=True)
class PortfolioSummary:
    user_id: int
    tracked_properties: int
    unread_alert_count: int
    items: tuple[PortfolioItem, ...]
    average_avm_variation: PortfolioTrendState
    upside: PortfolioUpsideState
    history: PortfolioHistoryState
    compared: PortfolioComparedState
    favorites: PortfolioFavoriteState
    recommendations: PortfolioRecommendationState

    def to_payload(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "tracked_properties": self.tracked_properties,
            "unread_alert_count": self.unread_alert_count,
            "items": [item.to_payload() for item in self.items],
            "average_avm_variation": self.average_avm_variation.to_payload(),
            "upside": self.upside.to_payload(),
            "history": self.history.to_payload(),
            "compared": self.compared.to_payload(),
            "favorites": self.favorites.to_payload(),
            "recommendations": self.recommendations.to_payload(),
        }


@dataclass(frozen=True)
class PortfolioItemValuationSnapshot:
    user_id: int
    listing_id: int
    watchlist_item_id: int | None
    valuation_id: int | None
    estimated_value_uf: Decimal | None
    estimated_value_clp: Decimal | None
    lower_bound_uf: Decimal | None
    upper_bound_uf: Decimal | None
    confidence: str | None
    engine_name: str | None
    engine_version: str | None
    valuation_source: str
    valuation_status: str
    unavailable_reason: str | None
    published_price_uf: Decimal | None
    published_price_clp: Decimal | None
    delta_uf: Decimal | None
    delta_pct: float | None
    delta_status: str
    delta_unavailable_reason: str | None
    data_freshness_status: str
    snapshot_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class PortfolioAggregateSnapshot:
    user_id: int
    snapshot_date: date
    total_estimated_value_uf: Decimal | None
    average_estimated_value_uf: Decimal | None
    total_published_price_uf: Decimal | None
    total_upside_uf: Decimal | None
    average_delta_pct: float | None
    item_count: int
    coverage_count: int
    unavailable_count: int
    snapshot_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class PortfolioValuationSnapshot:
    aggregate: PortfolioAggregateSnapshot
    items: tuple[PortfolioItemValuationSnapshot, ...] = field(default_factory=tuple)


def unavailable_avm_state() -> PortfolioItemAvmState:
    return PortfolioItemAvmState(
        status=PortfolioState.NEEDS_SNAPSHOT,
        reason="needs_portfolio_avm_snapshot",
    )


def unavailable_delta_state() -> PortfolioItemDeltaState:
    return PortfolioItemDeltaState(
        status=PortfolioState.NEEDS_VALUATION,
        reason="needs_current_valuation",
    )


def unavailable_trend_state() -> PortfolioTrendState:
    return PortfolioTrendState(
        status=PortfolioState.NEEDS_HISTORY,
        reason="needs_repeated_avm_snapshots",
    )


def unavailable_upside_state() -> PortfolioUpsideState:
    return PortfolioUpsideState(
        status=PortfolioState.NEEDS_SNAPSHOT,
        reason="needs_portfolio_avm_snapshot",
    )


def unavailable_history_state() -> PortfolioHistoryState:
    return PortfolioHistoryState(
        status=PortfolioState.NEEDS_HISTORY,
        reason="needs_repeated_avm_snapshots",
    )


def unavailable_compared_state() -> PortfolioComparedState:
    return PortfolioComparedState(
        status=PortfolioState.NOT_AVAILABLE,
        reason="needs_compared_event_model",
    )


def unavailable_favorite_state() -> PortfolioFavoriteState:
    return PortfolioFavoriteState(
        status=PortfolioState.NOT_AVAILABLE,
        reason="needs_favorites_model",
    )


def unavailable_recommendation_state() -> PortfolioRecommendationState:
    return PortfolioRecommendationState(
        status=PortfolioState.NOT_AVAILABLE,
        reason="portfolio_recommendation_engine_not_implemented",
    )


def _decimal_or_none(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _datetime_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
