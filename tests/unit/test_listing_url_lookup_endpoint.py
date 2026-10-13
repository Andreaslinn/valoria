from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import deps
from api.rate_limit import RateLimiter
from api.v1 import listings as listings_api
from config import get_settings
from core.entities.user import User


@dataclass(frozen=True)
class _LookupResult:
    status: str
    listing_data: dict[str, Any]
    warnings: list[str]
    source: str | None
    url: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "listing_data": self.listing_data,
            "warnings": self.warnings,
            "source": self.source,
            "url": self.url,
        }


def _client(*, authenticated: bool = True) -> TestClient:
    app = FastAPI()

    async def _db_override():
        yield None

    if authenticated:
        app.dependency_overrides[deps._resolve_current_user] = _authenticated_user
    settings = get_settings().model_copy(update={"rate_limit_enabled": False})
    app.dependency_overrides[deps.get_db] = _db_override
    app.dependency_overrides[deps.get_uf_service] = lambda: object()
    app.dependency_overrides[deps.get_rate_limiter] = lambda: RateLimiter(redis=None, settings=settings)
    app.include_router(listings_api.router, prefix="/api/v1")
    return TestClient(app)


async def _authenticated_user() -> User:
    return User(
        id=1,
        email="lookup-user@example.com",
        password_hash="hash",
        role="beta_user",
        is_active=True,
    )


def test_lookup_url_authenticated_happy_path_mocking_service(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_lookup(url: str) -> _LookupResult:
        calls.append(url)
        return _LookupResult(
            status="parsed_new",
            listing_data={
                "title": "Depto Yapo",
                "comuna": "nunoa",
                "m2": 70,
                "precio_publicado_clp": 120_000_000,
            },
            warnings=[],
            source="yapo",
            url=url,
        )

    monkeypatch.setattr(listings_api, "lookup_listing_url", fake_lookup)

    response = _client().post(
        "/api/v1/listings/lookup-url",
        json={"url": " https://www.yapo.cl/metropolitana/departamento-test "},
    )

    assert response.status_code == 200
    assert calls == ["https://www.yapo.cl/metropolitana/departamento-test"]
    body = response.json()
    assert body | {
        "freshness_status": None,
        "last_seen_at": None,
        "last_refreshed_at": None,
        "last_refresh_status": None,
        "freshness_note": None,
        "refresh_attempted": False,
        "refresh_result": None,
    } == body
    assert {
        key: body[key]
        for key in ("status", "listing_data", "warnings", "source", "url")
    } == {
        "status": "parsed_new",
        "listing_data": {
            "thumbnail": None,
            "title": "Depto Yapo",
            "comuna": "nunoa",
            "m2": 70,
            "precio_publicado_clp": 120_000_000,
        },
        "warnings": [],
        "source": "yapo",
        "url": "https://www.yapo.cl/metropolitana/departamento-test",
    }


def test_lookup_url_without_authenticated_user_returns_401(monkeypatch) -> None:
    async def fake_lookup(url: str) -> _LookupResult:
        raise AssertionError("lookup service should not be called without auth")

    monkeypatch.setattr(listings_api, "lookup_listing_url", fake_lookup)

    response = _client(authenticated=False).post(
        "/api/v1/listings/lookup-url",
        json={"url": "https://www.yapo.cl/metropolitana/departamento-test"},
    )

    assert response.status_code in {401, 403}


def test_lookup_url_empty_url_returns_400(monkeypatch) -> None:
    async def fake_lookup(url: str) -> _LookupResult:
        raise AssertionError("lookup service should not be called for empty URLs")

    monkeypatch.setattr(listings_api, "lookup_listing_url", fake_lookup)

    response = _client().post("/api/v1/listings/lookup-url", json={"url": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "URL requerida"


def test_lookup_url_unsupported_source_returns_400(monkeypatch) -> None:
    async def fake_lookup(url: str) -> _LookupResult:
        return _LookupResult(
            status="unsupported_source",
            listing_data={},
            warnings=["Fuente aun no soportada"],
            source=None,
            url=url,
        )

    monkeypatch.setattr(listings_api, "lookup_listing_url", fake_lookup)

    response = _client().post(
        "/api/v1/listings/lookup-url",
        json={"url": "https://example.com/listing/123"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Fuente aun no soportada"


def test_lookup_url_parse_failure_returns_502(monkeypatch) -> None:
    async def fake_lookup(url: str) -> _LookupResult:
        return _LookupResult(
            status="failed",
            listing_data={},
            warnings=["No se pudo parsear la publicacion"],
            source="yapo",
            url=url,
        )

    monkeypatch.setattr(listings_api, "lookup_listing_url", fake_lookup)

    response = _client().post(
        "/api/v1/listings/lookup-url",
        json={"url": "https://www.yapo.cl/metropolitana/listing-roto"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "No se pudo parsear la publicacion"


def test_analyze_url_authenticated_happy_path_mocking_services(monkeypatch) -> None:
    class FakeValuationService:
        async def valuate_property(self, valuation_input, *, valuation_strategy: str = "current"):
            assert valuation_input.comuna == "nunoa"
            assert valuation_input.precio_publicado_uf == 4300
            assert valuation_strategy == "consensus_v1"

            class Result:
                estimated_price_uf = 5000
                estimated_price_clp = 200_000_000
                price_range_low_uf = 4500
                price_range_high_uf = 5500
                confidence_score = 0.72
                confidence_label = "medium"
                comparable_count = 12
                warnings = ()

            return Result()

    async def fake_lookup(url: str) -> _LookupResult:
        return _LookupResult(
            status="found_existing",
            listing_data={
                "listing_id": 123,
                "title": "Depto Yapo",
                "url": url,
                "comuna": "nunoa",
                "property_type": "apartment",
                "m2": 70,
                "built_area_m2": 70,
                "usable_area_m2": 70,
                "dormitorios": 2,
                "banos": 2,
                "estacionamientos": 1,
                "precio_publicado_uf": 4300,
                "precio_publicado_clp": 167_700_000,
                "price_currency": "UF",
                "price_uf_source": "scraped",
                "price_uf_confidence": "high",
            },
            warnings=[],
            source="yapo",
            url=url,
        )

    monkeypatch.setattr(listings_api, "lookup_listing_url", fake_lookup)
    client = _client()
    client.app.dependency_overrides[deps.get_valuation_service] = lambda: FakeValuationService()

    response = client.post(
        "/api/v1/listings/analyze-url",
        json={"url": "https://www.yapo.cl/metropolitana/departamento-test"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["listing"]["listing_id"] == 123
    assert body["price_analysis"]["verdict"] == "under_market"
    assert body["valuation"]["estimated_value_uf"] == 5000
    assert body["report_status"]["listing_risk_report_available"] is False
