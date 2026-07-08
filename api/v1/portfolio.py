"""Authenticated Portfolio backend skeleton endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from api.deps import (
    CurrentUser,
    PortfolioComparisonServiceDep,
    PortfolioServiceDep,
    PortfolioSnapshotServiceDep,
)
from services.portfolio_comparisons import PortfolioComparisonError

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


class PortfolioPayloadOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_id: int
    tracked_properties: int | None = None


class PortfolioItemsOut(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)


class PortfolioSnapshotRunIn(BaseModel):
    dry_run: bool = True
    limit: int | None = Field(default=20, ge=1, le=100)


class PortfolioSnapshotRunOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_id: int
    dry_run: bool
    processed_count: int
    valued_count: int
    unavailable_count: int


class PortfolioComparisonCreateIn(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class PortfolioComparisonItemIn(BaseModel):
    listing_id: int | None = None
    watchlist_item_id: int | None = None


class PortfolioComparisonOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    comparison: dict[str, Any]
    items: list[dict[str, Any]] = Field(default_factory=list)


class PortfolioComparisonListOut(BaseModel):
    comparisons: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/summary", response_model=PortfolioPayloadOut)
async def get_portfolio_summary(
    current_user: CurrentUser,
    service: PortfolioServiceDep,
) -> PortfolioPayloadOut:
    assert current_user.id is not None
    summary = await service.build_summary(user_id=current_user.id)
    return PortfolioPayloadOut.model_validate(summary.to_payload())


@router.get("/items", response_model=PortfolioItemsOut)
async def get_portfolio_items(
    current_user: CurrentUser,
    service: PortfolioServiceDep,
) -> PortfolioItemsOut:
    assert current_user.id is not None
    items = await service.build_items(user_id=current_user.id)
    return PortfolioItemsOut(items=[item.to_payload() for item in items])


@router.get("/capabilities", response_model=PortfolioPayloadOut)
async def get_portfolio_capabilities(
    current_user: CurrentUser,
    service: PortfolioServiceDep,
) -> PortfolioPayloadOut:
    assert current_user.id is not None
    payload = await service.build_capabilities(user_id=current_user.id)
    return PortfolioPayloadOut.model_validate(payload)


@router.post("/snapshots", response_model=PortfolioSnapshotRunOut)
async def create_portfolio_snapshot(
    payload: PortfolioSnapshotRunIn,
    current_user: CurrentUser,
    service: PortfolioSnapshotServiceDep,
) -> PortfolioSnapshotRunOut:
    assert current_user.id is not None
    result = await service.create_snapshot(
        user_id=current_user.id,
        limit=payload.limit,
        dry_run=payload.dry_run,
    )
    return PortfolioSnapshotRunOut.model_validate(result.to_payload())


@router.get("/comparisons", response_model=PortfolioComparisonListOut)
async def list_portfolio_comparisons(
    current_user: CurrentUser,
    service: PortfolioComparisonServiceDep,
) -> PortfolioComparisonListOut:
    assert current_user.id is not None
    comparisons = await service.list_comparisons(user_id=current_user.id)
    return PortfolioComparisonListOut(comparisons=comparisons)


@router.post("/comparisons", response_model=PortfolioComparisonOut)
async def create_portfolio_comparison(
    payload: PortfolioComparisonCreateIn,
    current_user: CurrentUser,
    service: PortfolioComparisonServiceDep,
) -> PortfolioComparisonOut:
    assert current_user.id is not None
    return PortfolioComparisonOut.model_validate(
        await service.create_comparison(user_id=current_user.id, title=payload.title)
    )


@router.get("/comparisons/{comparison_id}", response_model=PortfolioComparisonOut)
async def get_portfolio_comparison(
    comparison_id: int,
    current_user: CurrentUser,
    service: PortfolioComparisonServiceDep,
) -> PortfolioComparisonOut:
    assert current_user.id is not None
    try:
        return PortfolioComparisonOut.model_validate(
            await service.get_comparison(user_id=current_user.id, comparison_id=comparison_id)
        )
    except PortfolioComparisonError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/comparisons/{comparison_id}/items", response_model=PortfolioComparisonOut)
async def add_portfolio_comparison_item(
    comparison_id: int,
    payload: PortfolioComparisonItemIn,
    current_user: CurrentUser,
    service: PortfolioComparisonServiceDep,
) -> PortfolioComparisonOut:
    assert current_user.id is not None
    try:
        return PortfolioComparisonOut.model_validate(
            await service.add_item(
                user_id=current_user.id,
                comparison_id=comparison_id,
                listing_id=payload.listing_id,
                watchlist_item_id=payload.watchlist_item_id,
            )
        )
    except PortfolioComparisonError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.delete("/comparisons/{comparison_id}/items/{item_id}", response_model=PortfolioComparisonOut)
async def remove_portfolio_comparison_item(
    comparison_id: int,
    item_id: int,
    current_user: CurrentUser,
    service: PortfolioComparisonServiceDep,
) -> PortfolioComparisonOut:
    assert current_user.id is not None
    try:
        return PortfolioComparisonOut.model_validate(
            await service.remove_item(user_id=current_user.id, comparison_id=comparison_id, item_id=item_id)
        )
    except PortfolioComparisonError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/comparisons/{comparison_id}/report.html", response_class=HTMLResponse)
async def get_portfolio_comparison_report_html(
    comparison_id: int,
    current_user: CurrentUser,
    service: PortfolioComparisonServiceDep,
) -> HTMLResponse:
    assert current_user.id is not None
    try:
        html = await service.build_report_html(user_id=current_user.id, comparison_id=comparison_id)
    except PortfolioComparisonError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return HTMLResponse(content=html)
