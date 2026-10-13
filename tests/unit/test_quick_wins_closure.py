"""Final bounded quick wins: unavailable UF and invalid report estimates."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI

from api import deps
from api.v1 import listings, radar, reports, valuations
from infrastructure.db.database import get_db
from core.exceptions import UFServiceError
from services import reports as report_service


@pytest.mark.parametrize("route,method,payload", [
    ("/valuations", "POST", {"comuna": "nunoa", "m2": 75}),
    ("/radar/opportunities", "GET", None),
    ("/listings/analyze-url", "POST", {"url": "https://www.yapo.cl/anuncio/123"}),
])
async def test_uf_unavailable_has_specific_http_contract(monkeypatch, route, method, payload):
    app = FastAPI()
    for router in (valuations.router, radar.router, listings.router):
        app.include_router(router)
    unavailable = AsyncMock(side_effect=UFServiceError("private provider diagnostic"))
    app.dependency_overrides[deps._resolve_current_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[deps.get_valuation_service] = lambda: SimpleNamespace(valuate_property=unavailable)
    app.dependency_overrides[deps.get_radar_service] = lambda: SimpleNamespace(opportunities=unavailable)
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[deps.get_uf_service] = lambda: None
    monkeypatch.setattr(listings, "lookup_listing_url", AsyncMock(return_value=SimpleNamespace(
        status="found_existing", listing_data={"comuna": "nunoa", "m2": 75, "listing_id": 1})))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.request(method, route, json=payload)
    assert response.status_code == 503
    assert response.json() == {"detail": "UF real no disponible"}
    unavailable.assert_awaited_once()


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), -float("inf"), "NaN", "Infinity"])
@pytest.mark.parametrize("kind", ["valuation", "listing"])
@pytest.mark.parametrize("currency", ["uf", "clp"])
def test_invalid_report_estimate_rejected_before_render(monkeypatch, value, kind, currency):
    renderer = Mock(return_value="<html></html>")
    monkeypatch.setattr(report_service, "build_risk_report_html", renderer)
    prefix = "estimated_price" if kind == "valuation" else "estimated_value"
    estimate = {f"{prefix}_{currency}": value}
    # A valid second currency must not hide the invalid estimate.
    estimate[f"{prefix}_{'clp' if currency == 'uf' else 'uf'}"] = 5000
    with pytest.raises(report_service.ReportGenerationError):
        if kind == "valuation":
            report_service.build_property_valuation_report_html(valuation_result=estimate, valuation_payload={})
        else:
            report_service.build_listing_analysis_report_html(analysis={"valuation": estimate})
    renderer.assert_not_called()


@pytest.mark.parametrize("estimate", [{"estimated_price_uf": 5000}, {"estimated_price_clp": 200000000},
                                      {"estimated_price_uf": 5000, "estimated_price_clp": 200000000}])
def test_valid_report_estimates_remain_accepted(estimate):
    assert "html" in report_service.build_property_valuation_report_html(
        valuation_result=estimate, valuation_payload={}).lower()


@pytest.mark.parametrize("value", [0, -1, "NaN", "Infinity"])
@pytest.mark.parametrize("kind", ["valuation", "listing-analysis"])
async def test_invalid_report_payload_returns_422(kind, value):
    app = FastAPI()
    app.include_router(reports.router)
    app.dependency_overrides[deps._resolve_current_user] = lambda: SimpleNamespace(id=1)
    payload = ({"valuation_result": {"estimated_price_uf": value}} if kind == "valuation"
               else {"analysis": {"valuation": {"estimated_value_uf": value}}})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/reports/{kind}", json=payload)
    assert response.status_code == 422
    assert "finito y positivo" in response.json()["detail"]
