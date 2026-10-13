"""Basic API endpoint coverage for module 7."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.deps import get_uf_service
from api.main import create_app
from api.security import hash_password
from core.entities.listing import Listing
from core.entities.user import User
from core.ports.uf_service import UFService
from core.value_objects.location import Coordinates
from core.value_objects.price import Price
from infrastructure.db.database import get_db
from infrastructure.db.models import PriceHistoryORM
from infrastructure.db.repositories import SqlAlchemyListingRepository, SqlAlchemyUserRepository


class FakeUFService(UFService):
    async def get_current_rate(self) -> Decimal:
        return Decimal("39000")


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
    app.dependency_overrides[get_uf_service] = lambda: FakeUFService()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def seeded_listings(engine: AsyncEngine) -> list[Listing]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    saved: list[Listing] = []
    async with session_factory() as session:
        repo = SqlAlchemyListingRepository(session)
        for idx in range(12):
            price = 120_000_000 if idx == 0 else 180_000_000 + idx * 1_000_000
            saved.append(
                await repo.save(
                    Listing(
                        id=None,
                        source="yapo",
                        external_id=f"api-{idx}",
                        title=f"Depto test {idx}",
                        comuna="nunoa",
                        m2=74.0 + (idx % 3),
                        property_type="apartment",
                        bedrooms=3,
                        bathrooms=2,
                        parking=1,
                        price=Price(clp=Decimal(str(price))),
                        price_currency="CLP",
                        status="active",
                        fingerprint=f"api-fp-{idx}",
                        scraped_at=datetime.now(UTC),
                        coordinates=Coordinates(lat=-33.4569, lon=-70.5969),
                        geocode_precision="address",
                        url=f"https://example.test/{idx}",
                    )
                )
            )
        await session.commit()
    return saved


@pytest_asyncio.fixture
async def auth_headers(engine: AsyncEngine, client: httpx.AsyncClient) -> dict[str, str]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        repo = SqlAlchemyUserRepository(session)
        await repo.save(
            User(
                id=None,
                email="api-user@example.com",
                password_hash=hash_password("passwordsegura123"),
                role="beta_user",
                is_active=True,
            )
        )
        await session.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "api-user@example.com", "password": "passwordsegura123"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_health_endpoint(client: httpx.AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_market_uf_endpoint_uses_central_service(client: httpx.AsyncClient):
    resp = await client.get("/api/v1/market/uf")

    assert resp.status_code == 200
    body = resp.json()
    assert body["rate_clp"] == 39000.0
    assert body["source"] == "service"
    assert body["is_fallback"] is False
    assert body["cache_ttl_seconds"] == 86400


async def test_listings_endpoint_returns_list(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    seeded_listings: list[Listing],
):
    resp = await client.get("/api/v1/listings", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 12
    assert body[0]["comuna"] == "nunoa"
    assert body[0]["price_uf"] is None
    assert body[0]["price_uf_display"] is not None
    assert body[0]["price_display_basis"] == "canonical_clp"
    assert body[0]["price_clp_display"] == body[0]["price_clp"]
    assert body[0]["uf_rate_used_for_display"] == 39000.0


async def test_listing_api_exposes_canonical_uf_only(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    engine: AsyncEngine,
):
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        repo = SqlAlchemyListingRepository(session)
        canonical = await repo.save(
            Listing(
                id=None,
                source="yapo",
                external_id="api-canonical-uf",
                title="Depto UF canonico",
                comuna="nunoa",
                m2=72,
                bedrooms=2,
                bathrooms=2,
                parking=1,
                price=Price(clp=Decimal("156000000")),
                price_uf=Decimal("4000"),
                price_currency="UF",
                price_uf_source="scraped",
                price_uf_confidence="high",
                price_recovery_method="raw_metadata.price_uf",
                status="active",
                fingerprint="api-canonical-uf-fp",
                scraped_at=datetime.now(UTC),
                url="https://example.test/api-canonical-uf",
            )
        )
        legacy = await repo.save(
            Listing(
                id=None,
                source="yapo",
                external_id="api-legacy-uf",
                title="Depto UF legacy",
                comuna="nunoa",
                m2=72,
                bedrooms=2,
                bathrooms=2,
                parking=1,
                price=Price(clp=Decimal("156000000")),
                price_currency="UF",
                price_uf_source="legacy_unrecoverable",
                price_recovery_method="legacy_unrecoverable",
                status="active",
                fingerprint="api-legacy-uf-fp",
                scraped_at=datetime.now(UTC),
                url="https://example.test/api-legacy-uf",
            )
        )
        await session.commit()

    canonical_resp = await client.get(f"/api/v1/listings/{canonical.id}", headers=auth_headers)
    legacy_resp = await client.get(f"/api/v1/listings/{legacy.id}", headers=auth_headers)

    assert canonical_resp.status_code == 200
    canonical_body = canonical_resp.json()
    assert canonical_body["price_uf"] == 4000.0
    assert canonical_body["price_uf_display"] == 4000.0
    assert canonical_body["price_display_basis"] == "canonical_uf"
    assert canonical_body["price_clp_snapshot"] == 156_000_000
    assert canonical_body["price_clp_display"] == 156_000_000
    assert canonical_body["price_uf_source"] == "scraped"
    assert legacy_resp.status_code == 200
    legacy_body = legacy_resp.json()
    assert legacy_body["price_uf"] is None
    assert legacy_body["price_uf_display"] == 4000.0
    assert legacy_body["price_display_basis"] == "derived_display"
    assert legacy_body["price_clp_snapshot"] == 156_000_000


async def test_listings_endpoint_allows_incomplete_m2(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    engine: AsyncEngine,
):
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        repo = SqlAlchemyListingRepository(session)
        saved = await repo.save(
            Listing(
                id=None,
                source="yapo",
                external_id="api-incomplete",
                title="Depto sin superficie",
                comuna="nunoa",
                m2=None,
                property_type="apartment",
                bedrooms=2,
                bathrooms=1,
                parking=0,
                price=Price(clp=Decimal("120000000")),
                status="active",
                fingerprint="api-incomplete-fp",
                scraped_at=datetime.now(UTC),
                url="https://example.test/incomplete",
            )
        )
        await session.commit()

    resp = await client.get("/api/v1/listings", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    item = next(row for row in body if row["id"] == saved.id)
    assert item["m2"] is None


async def test_listing_detail_not_found(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
):
    resp = await client.get("/api/v1/listings/999999", headers=auth_headers)
    assert resp.status_code == 404


async def test_listing_price_history_requires_auth(client: httpx.AsyncClient):
    resp = await client.get("/api/v1/listings/1/price-history")

    assert resp.status_code in {401, 403}


async def test_listing_price_history_not_found(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
):
    resp = await client.get("/api/v1/listings/999999/price-history", headers=auth_headers)

    assert resp.status_code == 404


async def test_listing_price_history_returns_ordered_points(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    engine: AsyncEngine,
):
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    observed_at = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    async with session_factory() as session:
        repo = SqlAlchemyListingRepository(session)
        listing = await repo.save(
            Listing(
                id=None,
                source="yapo",
                external_id="api-price-history",
                title="Depto con historial",
                comuna="nunoa",
                m2=75,
                bedrooms=3,
                bathrooms=2,
                parking=1,
                price=Price(clp=Decimal("160000000")),
                status="active",
                fingerprint="api-price-history-fp",
                scraped_at=observed_at.replace(day=8),
                url="https://example.test/price-history",
            )
        )
        session.add_all(
            [
                PriceHistoryORM(
                    listing_id=listing.id,
                    price_clp=Decimal("170000000"),
                    observed_at=observed_at.replace(day=5),
                ),
                PriceHistoryORM(
                    listing_id=listing.id,
                    price_clp=Decimal("180000000"),
                    observed_at=observed_at,
                ),
            ]
        )
        await session.commit()

    resp = await client.get(f"/api/v1/listings/{listing.id}/price-history", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["listing_id"] == listing.id
    assert [point["price_clp"] for point in body["points"]] == [
        180_000_000,
        170_000_000,
        160_000_000,
    ]
    assert [point["point_type"] for point in body["points"]] == [
        "historical",
        "historical",
        "current",
    ]
    assert body["points"][0]["price_uf"] is None
    assert body["points"][-1]["source"] == "yapo"
    assert body["points"][-1]["source_url"] == "https://example.test/price-history"
    assert body["points"][0]["is_artifact"] is False
    assert "change_basis" in body["points"][0]
    assert "price_currency" in body["points"][0]


async def test_listing_price_history_without_history_returns_current_point(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    engine: AsyncEngine,
):
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    observed_at = datetime(2026, 5, 10, 10, 0, tzinfo=UTC)
    async with session_factory() as session:
        repo = SqlAlchemyListingRepository(session)
        listing = await repo.save(
            Listing(
                id=None,
                source="yapo",
                external_id="api-price-history-current",
                title="Depto sin historial",
                comuna="nunoa",
                m2=75,
                bedrooms=3,
                bathrooms=2,
                parking=1,
                price=Price(clp=Decimal("150000000")),
                status="active",
                fingerprint="api-price-history-current-fp",
                scraped_at=observed_at,
                url="https://example.test/price-history-current",
            )
        )
        await session.commit()

    resp = await client.get(f"/api/v1/listings/{listing.id}/price-history", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["listing_id"] == listing.id
    assert body["points"] == [
        {
            "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
            "price_clp": 150_000_000,
            "price_uf": None,
            "price_clp_snapshot": 150_000_000,
            "price_currency": None,
            "change_basis": None,
            "is_artifact": False,
            "artifact_reason": None,
            "source": "yapo",
            "source_url": "https://example.test/price-history-current",
            "point_type": "current",
        }
    ]


async def test_listing_price_history_filters_artifacts_by_default(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    engine: AsyncEngine,
):
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    observed_at = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    async with session_factory() as session:
        repo = SqlAlchemyListingRepository(session)
        listing = await repo.save(
            Listing(
                id=None,
                source="yapo",
                external_id="api-price-history-artifact",
                title="Depto artifact",
                comuna="nunoa",
                m2=75,
                bedrooms=3,
                bathrooms=2,
                parking=1,
                price=Price(clp=Decimal("160000000")),
                price_uf=Decimal("4000"),
                price_currency="UF",
                price_uf_source="scraped",
                status="active",
                fingerprint="api-price-history-artifact-fp",
                scraped_at=observed_at.replace(day=8),
                url="https://example.test/price-history-artifact",
            )
        )
        session.add(
            PriceHistoryORM(
                listing_id=listing.id,
                price_clp=Decimal("148000000"),
                price_clp_snapshot=Decimal("148000000"),
                price_uf=Decimal("4000"),
                price_currency="UF",
                change_basis="uf_rate_artifact",
                is_artifact=True,
                artifact_reason="uf_rate_artifact",
                observed_at=observed_at,
            )
        )
        await session.commit()

    default_resp = await client.get(f"/api/v1/listings/{listing.id}/price-history", headers=auth_headers)
    include_resp = await client.get(
        f"/api/v1/listings/{listing.id}/price-history?include_artifacts=true",
        headers=auth_headers,
    )

    assert default_resp.status_code == 200
    assert len(default_resp.json()["points"]) == 1
    assert default_resp.json()["points"][0]["point_type"] == "current"
    assert include_resp.status_code == 200
    artifact = include_resp.json()["points"][0]
    assert artifact["is_artifact"] is True
    assert artifact["artifact_reason"] == "uf_rate_artifact"
    assert artifact["change_basis"] == "uf_rate_artifact"


async def test_market_price_m2_trend_endpoint_returns_real_points(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    engine: AsyncEngine,
):
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        repo = SqlAlchemyListingRepository(session)
        listings: list[Listing] = []
        for index in range(3):
            listings.append(
                await repo.save(
                    Listing(
                        id=None,
                        source="yapo",
                        external_id=f"trend-{index}",
                        title=f"Depto trend {index}",
                        comuna="providencia",
                        property_type="apartment",
                        m2=50,
                        bedrooms=2,
                        bathrooms=2,
                        parking=1,
                        price=Price(clp=Decimal("200000000")),
                        price_uf=Decimal("5000"),
                        price_currency="UF",
                        price_uf_source="scraped",
                        status="active",
                        fingerprint=f"trend-{index}",
                        scraped_at=datetime(2026, 6, 15, tzinfo=UTC),
                    )
                )
            )
        for month, base in enumerate([80, 82, 84], start=1):
            for offset, listing in enumerate(listings):
                session.add(
                    PriceHistoryORM(
                        listing_id=listing.id,
                        price_clp=Decimal("200000000"),
                        price_uf=Decimal(str((base + offset) * 50)),
                        price_clp_snapshot=Decimal("200000000"),
                        price_currency="UF",
                        change_basis="uf",
                        is_artifact=False,
                        observed_at=datetime(2026, month, 15, tzinfo=UTC),
                    )
                )
        await session.commit()

    resp = await client.get(
        "/api/v1/market/trends/price-m2?comuna=providencia&property_type=apartment&period_months=12",
        headers=auth_headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "partial"
    assert body["metric"] == "price_m2_uf"
    assert body["source"] == "price_history"
    assert body["points"][0] == {
        "month": "2026-01",
        "median_price_m2_uf": 81.0,
        "sample_count": 3,
    }
    assert body["coverage_count"] == 9


async def test_valuation_endpoint_valid_input(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    seeded_listings: list[Listing],
):
    resp = await client.post(
        "/api/v1/valuations",
        headers=auth_headers,
        json={
            "comuna": "nunoa",
            "property_type": "departamento",
            "m2": 75.0,
            "dormitorios": 3,
            "banos": 2,
            "estacionamientos": 1,
            "precio_publicado_uf": 4500.0,
        },
    )
    assert resp.status_code not in {401, 403}
    if resp.status_code != 200:
        return
    body = resp.json()
    assert body["status"] == "ok"
    assert body["estimated_price_clp"] > 0
    assert body["price_range_low_uf"] is not None
    assert body["price_range_high_uf"] is not None
    assert body["comparable_count"] >= 5


async def test_valuation_endpoint_exposes_beta_consensus_when_enabled(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    seeded_listings: list[Listing],
    engine: AsyncEngine,
    monkeypatch,
):
    monkeypatch.setenv("VALORIA_USE_CONSENSUS", "true")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        repo = SqlAlchemyListingRepository(session)
        for idx in range(8):
            await repo.save(
                Listing(
                    id=None,
                    source="yapo",
                    external_id=f"api-consensus-{idx}",
                    title=f"Depto consensus {idx}",
                    comuna="nunoa",
                    m2=75,
                    built_area_m2=75,
                    usable_area_m2=75,
                    property_type="apartment",
                    bedrooms=3,
                    bathrooms=2,
                    parking=1,
                    price=Price(clp=Decimal(str(180_000_000 + idx * 500_000))),
                    price_currency="CLP",
                    status="active",
                    fingerprint=f"api-consensus-fp-{idx}",
                    scraped_at=datetime.now(UTC),
                    url=f"https://example.test/consensus/{idx}",
                )
            )
        await session.commit()

    resp = await client.post(
        "/api/v1/valuations",
        headers=auth_headers,
        json={
            "comuna": "nunoa",
            "property_type": "departamento",
            "m2": 75.0,
            "dormitorios": 3,
            "banos": 2,
            "estacionamientos": 1,
            "precio_publicado_uf": 4500.0,
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valuation_strategy"] == "canonical_only"
    assert body["consensus_used"] is False
    assert body["consensus"] is None
    assert body["selected_engine_names"] == ["comparables_canonical_outliers"]
    assert body["consensus_method"] == "canonical_only_v1"
    assert {item["engine_name"] for item in body["engine_results"]} == {"comparables_canonical_outliers"}
    assert all("traceback" not in str(item).lower() for item in body["engine_results"])


async def test_valuation_endpoint_missing_m2_is_not_500(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
):
    resp = await client.post(
        "/api/v1/valuations",
        headers=auth_headers,
        json={"comuna": "nunoa", "property_type": "departamento"},
    )

    assert resp.status_code in {400, 422}


async def test_valuation_endpoint_null_m2_is_not_500(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
):
    resp = await client.post(
        "/api/v1/valuations",
        headers=auth_headers,
        json={"comuna": "nunoa", "property_type": "departamento", "m2": None},
    )

    assert resp.status_code in {400, 422}


async def test_radar_opportunities_endpoint(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    seeded_listings: list[Listing],
):
    resp = await client.get("/api/v1/radar/opportunities", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert body
    assert {
        "listing_id",
        "discount_pct",
        "score",
        "warnings",
        "allowed_property_types",
        "houses_on_hold_count",
        "radar_scope_note",
        "bedrooms",
        "bathrooms",
        "parking",
        "property_type",
        "price_uf_source",
        "uf_rate_used",
        "uf_rate_source",
        "uf_rate_stale",
        "lat",
        "lon",
        "geocode_precision",
    } <= set(body[0])
    assert body[0]["allowed_property_types"] == ["apartment"]
    assert body[0]["radar_scope_note"] == "Radar beta: por ahora analiza solo departamentos."
    assert body[0]["bedrooms"] == 3
    assert body[0]["bathrooms"] == 2
    assert body[0]["property_type"] == "apartment"
    assert body[0]["lat"] == -33.4569
    assert body[0]["lon"] == -70.5969
    assert body[0]["geocode_precision"] is not None
    assert body[0]["uf_rate_used"] == 39000.0
    assert body[0]["uf_rate_stale"] is False


async def test_radar_endpoint_skips_active_listing_without_area(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    seeded_listings: list[Listing],
    engine: AsyncEngine,
):
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        repo = SqlAlchemyListingRepository(session)
        await repo.save(
            Listing(
                id=None,
                source="yapo",
                external_id="api-invalid-area",
                title="Listing sin area",
                comuna="nunoa",
                m2=None,
                bedrooms=2,
                bathrooms=1,
                parking=0,
                price=Price(clp=Decimal("120000000")),
                status="active",
                fingerprint="api-invalid-area-fp",
                scraped_at=datetime.now(UTC),
                url="https://example.test/invalid-area",
            )
        )
        await session.commit()

    resp = await client.get("/api/v1/radar/opportunities", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert body
    assert all(item["title"] != "Listing sin area" for item in body)


async def test_listings_requires_auth(client: httpx.AsyncClient):
    resp = await client.get("/api/v1/listings")

    assert resp.status_code == 401


async def test_radar_requires_auth(client: httpx.AsyncClient):
    resp = await client.get("/api/v1/radar/opportunities")

    assert resp.status_code == 401


async def test_valuation_requires_auth(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/valuations",
        json={"comuna": "providencia", "property_type": "apartment", "m2": 65},
    )

    assert resp.status_code == 401
