"""Downloadable report endpoints."""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from api.deps import CurrentUser
from services.reports import (
    ReportGenerationError,
    build_listing_analysis_report_html,
    build_property_valuation_report_html,
    listing_analysis_filename,
    property_valuation_filename,
)

router = APIRouter(prefix="/reports", tags=["reports"])
_log = logging.getLogger(__name__)


class PropertyValuationReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valuation_result: dict[str, Any] = Field(default_factory=dict)
    valuation_payload: dict[str, Any] = Field(default_factory=dict)


class ListingAnalysisReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: dict[str, Any] = Field(default_factory=dict)


@router.post("/valuation")
async def download_property_valuation_report(
    payload: PropertyValuationReportRequest,
    _current_user: CurrentUser,
    format: Literal["html", "pdf"] = Query(default="html"),
) -> Response:
    if format == "pdf":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="PDF no disponible en esta fase; use format=html.",
        )
    try:
        html = build_property_valuation_report_html(
            valuation_result=payload.valuation_result,
            valuation_payload=payload.valuation_payload,
        )
    except ReportGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        _log.exception("Unexpected property valuation report error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error inesperado al generar informe de tasacion",
        ) from exc
    return _html_attachment_response(
        html,
        filename=property_valuation_filename(payload.valuation_payload),
    )


@router.post("/listing-analysis")
async def download_listing_analysis_report(
    payload: ListingAnalysisReportRequest,
    _current_user: CurrentUser,
    format: Literal["html", "pdf"] = Query(default="html"),
) -> Response:
    if format == "pdf":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="PDF no disponible en esta fase; use format=html.",
        )
    try:
        html = build_listing_analysis_report_html(analysis=payload.analysis)
    except ReportGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        _log.exception("Unexpected listing analysis report error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error inesperado al generar informe de publicacion",
        ) from exc
    return _html_attachment_response(
        html,
        filename=listing_analysis_filename(payload.analysis),
    )


def _html_attachment_response(html: str, *, filename: str) -> Response:
    return Response(
        content=html.encode("utf-8"),
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
