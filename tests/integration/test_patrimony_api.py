from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.main import create_app
from api.security import hash_password
from config import get_settings
from core.entities.user import User
from infrastructure.db.database import get_db
from infrastructure.db.models import (
    ListingORM,
    PatrimonyStrategyORM,
    PriceHistoryORM,
    PropertyAssetORM,
    PropertyValuationSnapshotORM,
    TerritorialDevelopmentORM,
)
from infrastructure.db.repositories import SqlAlchemyUserRepository


@pytest_asyncio.fixture
async def client(engine: AsyncEngine) -> AsyncGenerator[httpx.AsyncClient, None]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _get_db_override() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as s:
            try:
                yield s
            except Exception:
                await s.rollback()
                raise

    app = create_app()
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(update={"rate_limit_enabled": False})

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _auth_headers(engine: AsyncEngine, client: httpx.AsyncClient, email: str) -> dict[str, str]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        await SqlAlchemyUserRepository(session).save(
            User(
                id=None,
                email=email,
                password_hash=hash_password("passwordsegura123"),
                role="beta_user",
                is_active=True,
            )
        )
        await session.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "passwordsegura123"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _property_payload(name: str = "Casa Vitacura") -> dict:
    return {
        "name": name,
        "comuna": "Vitacura",
        "property_type": "departamento",
        "m2": 92,
        "built_area_m2": 92,
        "bedrooms": 3,
        "bathrooms": 2,
        "parking": 1,
        "characteristics": {
            "source": "tasar",
            "dormitorios": 3,
            "banos": 2,
            "estacionamientos": 1,
        },
        "valuation": {
            "estimated_value_uf": 8250,
            "estimated_value_clp": 321750000,
            "lower_bound_uf": 7900,
            "upper_bound_uf": 8600,
            "confidence": "high",
            "confidence_score": 0.82,
            "engine_name": "Valoria consensus",
            "engine_version": "consensus_v1",
        },
    }


async def test_create_property_with_initial_snapshot(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
):
    headers = await _auth_headers(engine, client, "owner@example.com")

    resp = await client.post("/api/v1/patrimony/properties", json=_property_payload(), headers=headers)

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Casa Vitacura"
    assert body["comuna"] == "vitacura"
    assert body["latest_valuation"]["estimated_value_uf"] == 8250.0
    assert body["latest_valuation"]["engine_version"] == "consensus_v1"
    assert len(body["valuation_snapshots"]) == 1

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        assets = (await session.execute(select(PropertyAssetORM))).scalars().all()
        snapshots = (await session.execute(select(PropertyValuationSnapshotORM))).scalars().all()
    assert len(assets) == 1
    assert len(snapshots) == 1
    assert snapshots[0].property_id == assets[0].id


async def test_list_properties_returns_only_current_user_items(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
):
    owner_headers = await _auth_headers(engine, client, "owner@example.com")
    other_headers = await _auth_headers(engine, client, "other@example.com")
    created = await client.post(
        "/api/v1/patrimony/properties",
        json=_property_payload("Casa propia"),
        headers=owner_headers,
    )
    assert created.status_code == 201
    other = await client.post(
        "/api/v1/patrimony/properties",
        json=_property_payload("Casa ajena"),
        headers=other_headers,
    )
    assert other.status_code == 201

    resp = await client.get("/api/v1/patrimony/properties", headers=owner_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert [item["name"] for item in body["items"]] == ["Casa propia"]


async def test_user_cannot_access_or_delete_another_users_property(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
):
    owner_headers = await _auth_headers(engine, client, "owner@example.com")
    other_headers = await _auth_headers(engine, client, "other@example.com")
    created = await client.post(
        "/api/v1/patrimony/properties",
        json=_property_payload(),
        headers=owner_headers,
    )
    property_id = created.json()["id"]

    get_resp = await client.get(f"/api/v1/patrimony/properties/{property_id}", headers=other_headers)
    intelligence_resp = await client.get(
        f"/api/v1/patrimony/properties/{property_id}/intelligence",
        headers=other_headers,
    )
    delete_resp = await client.delete(f"/api/v1/patrimony/properties/{property_id}", headers=other_headers)

    assert get_resp.status_code == 404
    assert intelligence_resp.status_code == 404
    assert delete_resp.status_code == 404
    owner_get = await client.get(f"/api/v1/patrimony/properties/{property_id}", headers=owner_headers)
    assert owner_get.status_code == 200


async def test_patch_property_adds_new_snapshot(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
):
    headers = await _auth_headers(engine, client, "owner@example.com")
    created = await client.post("/api/v1/patrimony/properties", json=_property_payload(), headers=headers)
    property_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/patrimony/properties/{property_id}",
        json={
            "valuation": {
                "estimated_value_uf": 8400,
                "lower_bound_uf": 8050,
                "upper_bound_uf": 8750,
                "confidence": "medium",
                "engine_name": "Valoria consensus",
                "engine_version": "consensus_v2",
            }
        },
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["latest_valuation"]["estimated_value_uf"] == 8400.0
    assert body["latest_valuation"]["engine_version"] == "consensus_v2"
    assert len(body["valuation_snapshots"]) == 2


async def test_property_intelligence_reuses_commune_market_signals(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
):
    headers = await _auth_headers(engine, client, "owner@example.com")
    created = await client.post("/api/v1/patrimony/properties", json=_property_payload(), headers=headers)
    property_id = created.json()["id"]
    await _seed_commune_market(engine, comuna="vitacura")

    resp = await client.get(f"/api/v1/patrimony/properties/{property_id}/intelligence", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "available"
    assert body["property_id"] == property_id
    assert body["buyer_seller_balance"]
    assert body["dynamism"] in {"Actividad baja", "Actividad moderada", "Actividad alta"}
    assert body["recommendation"] in {
        "maintain",
        "monitor",
        "prepare_sale",
        "evaluate_exit",
        "favorable_market",
    }
    assert body["reasons"]
    assert body["change_conditions"]
    assert body["signals"]["active_listings"] >= 30


async def test_property_intelligence_returns_insufficient_data_without_commune_sample(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
):
    headers = await _auth_headers(engine, client, "owner@example.com")
    created = await client.post("/api/v1/patrimony/properties", json=_property_payload(), headers=headers)
    property_id = created.json()["id"]

    resp = await client.get(f"/api/v1/patrimony/properties/{property_id}/intelligence", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "insufficient_data"
    assert body["recommendation"] is None
    assert body["confidence"] == "low"
    assert body["reasons"] == []


async def test_developments_list_and_property_association_by_commune(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
):
    headers = await _auth_headers(engine, client, "owner@example.com")
    created_property = await client.post("/api/v1/patrimony/properties", json=_property_payload(), headers=headers)
    property_id = created_property.json()["id"]
    await _seed_development(engine, comuna="vitacura")

    all_resp = await client.get("/api/v1/patrimony/developments", headers=headers)
    property_resp = await client.get(f"/api/v1/patrimony/properties/{property_id}/developments", headers=headers)
    intelligence_resp = await client.get(f"/api/v1/patrimony/properties/{property_id}/intelligence", headers=headers)

    assert all_resp.status_code == 200
    assert len(all_resp.json()["items"]) == 1
    assert property_resp.status_code == 200
    body = property_resp.json()
    assert body["items"][0]["name"] == "Proyecto conectividad Vitacura verificado"
    assert body["items"][0]["scenarios"]["favorable_max_pct"] == 15.0
    assert "podria alcanzar hasta 15" in body["items"][0]["scenarios"]["narrative"]
    assert intelligence_resp.status_code == 200
    intelligence = intelligence_resp.json()
    assert intelligence["territorial_developments"][0]["source"]["name"] == "Fuente verificada"
    assert intelligence["territorial_projection_message"].startswith("Proyeccion por escenarios")


async def test_property_developments_are_user_isolated_and_empty_when_no_match(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
):
    owner_headers = await _auth_headers(engine, client, "owner@example.com")
    other_headers = await _auth_headers(engine, client, "other@example.com")
    created_property = await client.post("/api/v1/patrimony/properties", json=_property_payload(), headers=owner_headers)
    property_id = created_property.json()["id"]
    other_property = await client.post(
        "/api/v1/patrimony/properties",
        json=_property_payload("Casa Nunoa") | {"comuna": "Nunoa"},
        headers=other_headers,
    )
    other_property_id = other_property.json()["id"]
    await _seed_development(engine, comuna="nunoa")

    forbidden = await client.get(f"/api/v1/patrimony/properties/{property_id}/developments", headers=other_headers)
    empty = await client.get(f"/api/v1/patrimony/properties/{property_id}/developments", headers=owner_headers)
    matched = await client.get(f"/api/v1/patrimony/properties/{other_property_id}/developments", headers=other_headers)

    assert forbidden.status_code == 404
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert matched.status_code == 200
    assert len(matched.json()["items"]) == 1


async def test_create_list_update_and_delete_strategy(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
):
    headers = await _auth_headers(engine, client, "owner@example.com")
    created_property = await client.post("/api/v1/patrimony/properties", json=_property_payload(), headers=headers)
    property_id = created_property.json()["id"]
    await _seed_commune_market(engine, comuna="vitacura")

    created = await client.post(
        "/api/v1/patrimony/strategies",
        json=_strategy_payload(property_id),
        headers=headers,
    )

    assert created.status_code == 201
    strategy = created.json()
    assert strategy["property_asset_id"] == property_id
    assert strategy["objective"] == "sell_and_buy"
    assert strategy["target_value_uf"] == 8800.0
    assert strategy["recommendation"]["status"] == "available"
    assert strategy["recommendation"]["current_recommendation"]
    assert strategy["recommendation"]["progress_to_target_pct"] == 93.8

    listed = await client.get("/api/v1/patrimony/strategies", headers=headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [strategy["id"]]

    patched = await client.patch(
        f"/api/v1/patrimony/strategies/{strategy['id']}",
        json={"objective": "maintain", "target_value_uf": None, "desired_communes": ["Nunoa"]},
        headers=headers,
    )
    assert patched.status_code == 200
    patched_body = patched.json()
    assert patched_body["objective"] == "maintain"
    assert patched_body["target_value_uf"] is None
    assert patched_body["desired_communes"] == ["nunoa"]
    assert patched_body["recommendation"]["progress_to_target_pct"] is None

    deleted = await client.delete(f"/api/v1/patrimony/strategies/{strategy['id']}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json() == {"id": strategy["id"], "deleted": True}
    missing = await client.get(f"/api/v1/patrimony/strategies/{strategy['id']}", headers=headers)
    assert missing.status_code == 404


async def test_strategy_requires_current_users_property_and_is_user_isolated(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
):
    owner_headers = await _auth_headers(engine, client, "owner@example.com")
    other_headers = await _auth_headers(engine, client, "other@example.com")
    created_property = await client.post("/api/v1/patrimony/properties", json=_property_payload(), headers=owner_headers)
    property_id = created_property.json()["id"]

    forbidden_create = await client.post(
        "/api/v1/patrimony/strategies",
        json=_strategy_payload(property_id),
        headers=other_headers,
    )
    assert forbidden_create.status_code == 404

    created = await client.post(
        "/api/v1/patrimony/strategies",
        json=_strategy_payload(property_id),
        headers=owner_headers,
    )
    strategy_id = created.json()["id"]

    other_get = await client.get(f"/api/v1/patrimony/strategies/{strategy_id}", headers=other_headers)
    other_patch = await client.patch(
        f"/api/v1/patrimony/strategies/{strategy_id}",
        json={"objective": "sell"},
        headers=other_headers,
    )
    other_delete = await client.delete(f"/api/v1/patrimony/strategies/{strategy_id}", headers=other_headers)

    assert other_get.status_code == 404
    assert other_patch.status_code == 404
    assert other_delete.status_code == 404


async def test_patrimony_alert_evaluation_deduplicates_and_lists_unread(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
):
    headers = await _auth_headers(engine, client, "alerts-owner@example.com")
    old_snapshot_at = (datetime.now(UTC) - timedelta(days=95)).isoformat()
    payload = _property_payload() | {
        "valuation": _property_payload()["valuation"] | {
            "estimated_value_uf": 8000,
            "snapshot_at": old_snapshot_at,
        }
    }
    created_property = await client.post("/api/v1/patrimony/properties", json=payload, headers=headers)
    property_id = created_property.json()["id"]
    stale_property = await client.post(
        "/api/v1/patrimony/properties",
        json=payload | {"name": "Casa stale"},
        headers=headers,
    )
    assert stale_property.status_code == 201
    await client.patch(
        f"/api/v1/patrimony/properties/{property_id}",
        json={"valuation": {"estimated_value_uf": 8400, "confidence": "high"}},
        headers=headers,
    )
    await client.post(
        "/api/v1/patrimony/strategies",
        json=_strategy_payload(property_id) | {"target_value_uf": 8300},
        headers=headers,
    )
    await _seed_development(engine, comuna="vitacura")

    first = await client.post("/api/v1/patrimony/alerts/evaluate", headers=headers)
    second = await client.post("/api/v1/patrimony/alerts/evaluate", headers=headers)
    listed = await client.get("/api/v1/patrimony/alerts", headers=headers)

    assert first.status_code == 200
    assert first.json()["created"] >= 1
    assert second.status_code == 200
    assert second.json()["created"] == 0
    body = listed.json()
    alert_types = {item["alert_type"] for item in body["items"]}
    assert {
        "valuation_refresh_due",
        "property_value_changed",
        "target_value_reached",
        "territorial_development_updated",
    }.issubset(alert_types)

    alert_id = body["items"][0]["id"]
    read = await client.patch(f"/api/v1/patrimony/alerts/{alert_id}/read", headers=headers)
    assert read.status_code == 200
    assert read.json()["read_at"] is not None
    after_read = await client.get("/api/v1/patrimony/alerts", headers=headers)
    assert alert_id not in {item["id"] for item in after_read.json()["items"]}


async def test_patrimony_alerts_are_user_isolated_and_dismissible(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
):
    owner_headers = await _auth_headers(engine, client, "alerts-owner@example.com")
    other_headers = await _auth_headers(engine, client, "alerts-other@example.com")
    created_property = await client.post("/api/v1/patrimony/properties", json=_property_payload(), headers=owner_headers)
    property_id = created_property.json()["id"]
    await client.patch(
        f"/api/v1/patrimony/properties/{property_id}",
        json={"valuation": {"estimated_value_uf": 9000, "confidence": "high"}},
        headers=owner_headers,
    )
    await client.post("/api/v1/patrimony/alerts/evaluate", headers=owner_headers)
    owner_alerts = await client.get("/api/v1/patrimony/alerts", headers=owner_headers)
    other_alerts = await client.get("/api/v1/patrimony/alerts", headers=other_headers)
    alert_id = owner_alerts.json()["items"][0]["id"]

    forbidden_read = await client.patch(f"/api/v1/patrimony/alerts/{alert_id}/read", headers=other_headers)
    dismissed = await client.patch(f"/api/v1/patrimony/alerts/{alert_id}/dismiss", headers=owner_headers)
    after_dismiss = await client.get("/api/v1/patrimony/alerts", headers=owner_headers)

    assert other_alerts.status_code == 200
    assert other_alerts.json()["items"] == []
    assert forbidden_read.status_code == 404
    assert dismissed.status_code == 200
    assert dismissed.json()["dismissed_at"] is not None
    assert alert_id not in {item["id"] for item in after_dismiss.json()["items"]}


async def test_strategy_review_due_alert_uses_user_strategy_only(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
):
    headers = await _auth_headers(engine, client, "strategy-review@example.com")
    created_property = await client.post("/api/v1/patrimony/properties", json=_property_payload(), headers=headers)
    property_id = created_property.json()["id"]
    created_strategy = await client.post(
        "/api/v1/patrimony/strategies",
        json=_strategy_payload(property_id) | {"horizon": "3 meses", "urgency": "medium"},
        headers=headers,
    )
    await _set_strategy_updated_at(engine, created_strategy.json()["id"], datetime.now(UTC) - timedelta(days=40))

    evaluated = await client.post("/api/v1/patrimony/alerts/evaluate", headers=headers)
    listed = await client.get("/api/v1/patrimony/alerts", headers=headers)

    assert evaluated.status_code == 200
    assert "strategy_review_due" in {item["alert_type"] for item in listed.json()["items"]}


def _strategy_payload(property_id: int) -> dict:
    return {
        "property_asset_id": property_id,
        "objective": "sell_and_buy",
        "horizon": "6 a 12 meses",
        "target_value_uf": 8800,
        "urgency": "medium",
        "risk_profile": "balanced",
        "next_move": "Preparar documentos y revisar presupuesto de compra.",
        "desired_property_type": "departamento",
        "desired_communes": ["Vitacura", "Las Condes"],
        "desired_budget_uf": 9200,
    }


async def _seed_commune_market(engine: AsyncEngine, *, comuna: str) -> None:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    now = datetime.now(UTC)
    async with session_factory() as session:
        for idx in range(1, 36):
            created = now - timedelta(days=idx % 14 + 20)
            session.add(
                _listing(
                    idx,
                    comuna=comuna,
                    created_at=created,
                    price_uf=Decimal("7200"),
                    usable_area_m2=72,
                )
            )
            if idx <= 18:
                session.add(_history(idx, now - timedelta(days=25), Decimal("7200")))
                session.add(_history(idx, now - timedelta(days=3), Decimal("7050")))
        await session.commit()


async def _seed_development(engine: AsyncEngine, *, comuna: str) -> None:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        session.add(
            TerritorialDevelopmentORM(
                name="Proyecto conectividad Vitacura verificado",
                development_type="connectivity",
                status="confirmed",
                description="Proyecto territorial con fuente verificada para tests.",
                affected_communes=[comuna],
                affected_microzones=[],
                expected_start_date=None,
                expected_completion_date=None,
                source_name="Fuente verificada",
                source_url="https://example.test/fuente",
                source_date=datetime.now(UTC).date(),
                confidence="medium",
                conservative_min_pct=Decimal("4.00"),
                conservative_max_pct=Decimal("7.00"),
                central_min_pct=Decimal("8.00"),
                central_max_pct=Decimal("11.00"),
                favorable_max_pct=Decimal("15.00"),
                methodology_note="Hipotesis metodologica configurable para escenarios, no crecimiento observado.",
                is_active=True,
            )
        )
        await session.commit()


async def _set_strategy_updated_at(engine: AsyncEngine, strategy_id: int, updated_at: datetime) -> None:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        strategy = await session.get(PatrimonyStrategyORM, strategy_id)
        assert strategy is not None
        strategy.updated_at = updated_at
        await session.commit()


def _listing(
    listing_id: int,
    *,
    comuna: str,
    created_at: datetime,
    price_uf: Decimal,
    usable_area_m2: float,
) -> ListingORM:
    return ListingORM(
        id=listing_id,
        source="test",
        external_id=f"patrimony-mi-{listing_id}",
        title=f"Listing {listing_id}",
        url=f"https://example.test/{listing_id}",
        comuna=comuna,
        property_type="apartment",
        m2=usable_area_m2,
        built_area_m2=usable_area_m2,
        usable_area_m2=usable_area_m2,
        land_area_m2=None,
        bedrooms=2,
        bathrooms=2,
        parking=1,
        lat=-33.4,
        lon=-70.6,
        geocode_precision="address",
        price_clp=price_uf * Decimal("40000"),
        price_uf=price_uf,
        price_currency="CLP",
        price_uf_confidence="high",
        price_uf_source="test",
        price_recovery_method=None,
        status="active",
        fingerprint=f"patrimony-mi-fingerprint-{listing_id}",
        raw_metadata={},
        scraped_at=created_at,
        last_seen_at=created_at,
        last_refresh_attempted_at=None,
        last_refresh_status=None,
        created_at=created_at,
        updated_at=created_at,
    )


def _history(listing_id: int, observed_at: datetime, price_uf: Decimal) -> PriceHistoryORM:
    return PriceHistoryORM(
        listing_id=listing_id,
        price_clp=price_uf * Decimal("40000"),
        price_uf=price_uf,
        price_clp_snapshot=price_uf * Decimal("40000"),
        price_currency="CLP",
        uf_rate_used=Decimal("40000"),
        change_basis="uf",
        is_artifact=False,
        artifact_reason=None,
        observed_at=observed_at,
    )
