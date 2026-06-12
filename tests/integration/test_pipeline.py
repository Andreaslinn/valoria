"""Tests de integración del pipeline de ingesta.

Corre contra los repos SQLAlchemy reales + SQLite in-memory. Verifica
el flujo completo end-to-end incluyendo deduplicación, reutilización
de Property, y registro de cambios de precio.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import UnknownComunaError, ValidationError
from domain.ingestion.pipeline import process_listing
from infrastructure.db.models import PriceHistoryORM, PropertyORM
from infrastructure.db.repositories import (
    SqlAlchemyListingRepository,
    SqlAlchemyPriceHistoryRepository,
    SqlAlchemyPropertyRepository,
)


# ─────────────────────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────────────────────
@pytest_asyncio.fixture
def repos(session: AsyncSession) -> dict:
    return {
        "listing_repo": SqlAlchemyListingRepository(session),
        "property_repo": SqlAlchemyPropertyRepository(session),
        "price_history_repo": SqlAlchemyPriceHistoryRepository(session),
    }


def _raw(**overrides) -> dict:
    base = {
        "source": "yapo",
        "external_id": "ext-abc",
        "title": "Depto 3D/2B Ñuñoa Centro",
        "comuna": "Ñuñoa",
        "m2": 75,
        "bedrooms": 3,
        "bathrooms": 2,
        "parking": 1,
        "price_clp": 180_000_000,
        "url": "https://yapo.cl/abc",
        "lat": -33.4569,
        "lon": -70.5969,
        "scraped_at": datetime(2026, 4, 23, 10, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────
#  Creación de listings nuevos
# ─────────────────────────────────────────────────────────
class TestCreateNewListing:
    async def test_inserts_listing_and_property(self, session: AsyncSession, repos):
        listing = await process_listing(_raw(), **repos)
        await session.commit()

        assert listing.id is not None
        assert listing.property_id is not None
        assert listing.property_type == "apartment"
        assert listing.price.clp == Decimal(180_000_000)
        assert listing.status == "active"
        assert listing.fingerprint  # no vacío

    async def test_new_listing_sets_last_seen_at(self, session: AsyncSession, repos):
        raw = _raw(scraped_at=datetime(2026, 4, 23, 10, 0, tzinfo=UTC))

        listing = await process_listing(raw, **repos)
        await session.commit()

        expected = raw["scraped_at"].replace(tzinfo=None)
        assert listing.last_seen_at == expected
        stored = await repos["listing_repo"].find_by_id(listing.id)
        assert stored is not None
        assert stored.last_seen_at == expected

    async def test_stores_coordinates(self, session: AsyncSession, repos):
        listing = await process_listing(_raw(), **repos)
        await session.commit()
        assert listing.coordinates is not None
        assert listing.coordinates.lat == pytest.approx(-33.4569)

    async def test_unknown_property_type_fallback_persists(self, session: AsyncSession, repos):
        listing = await process_listing(
            _raw(title="Propiedad amplia en Nunoa", comuna="Nunoa", external_id="unknown-type"),
            **repos,
        )
        await session.commit()

        assert listing.property_type == "unknown"
        stored = await repos["listing_repo"].find_by_id(listing.id)
        assert stored is not None
        assert stored.property_type == "unknown"

    async def test_persists_raw_metadata(self, session: AsyncSession, repos):
        raw = _raw(raw_metadata={"featured": True, "published_at": "2026-04-20"})
        listing = await process_listing(raw, **repos)
        await session.commit()
        assert listing.raw_metadata["featured"] is True
        assert listing.raw_metadata["published_at"] == "2026-04-20"

    async def test_allow_incomplete_persists_without_property(self, session: AsyncSession, repos):
        listing = await process_listing(
            _raw(comuna="Valparaíso", m2=0, title="Depto con vista al mar"),
            **repos,
            allow_incomplete=True,
        )
        await session.commit()

        assert listing.status == "incomplete"
        assert listing.m2 is None
        assert listing.property_id is None
        assert listing.raw_metadata["data_quality_warnings"] == [
            "missing_m2",
            "unknown_comuna",
        ]


# ─────────────────────────────────────────────────────────
#  Reutilización de Property (inmueble físico)
# ─────────────────────────────────────────────────────────
class TestPropertyReuse:
    async def test_same_physical_property_reuses_property_id(
        self, session: AsyncSession, repos
    ):
        """Dos listings con mismos atributos físicos → misma Property en DB."""
        first = await process_listing(_raw(external_id="yapo-1"), **repos)
        await session.commit()

        second = await process_listing(
            _raw(
                external_id="portal-1",
                source="portalinmobiliario",
                title="Depto centro nunoa OTRO ANUNCIO distinto",
                url="https://portalinmobiliario.com/xyz",
            ),
            **repos,
        )
        await session.commit()

        # Mismo Property aunque son listings diferentes
        assert first.property_id == second.property_id
        assert first.id != second.id

    async def test_different_physical_attrs_creates_new_property(
        self, session: AsyncSession, repos
    ):
        a = await process_listing(_raw(external_id="a"), **repos)
        await session.commit()

        # Diferentes bedrooms → otro inmueble
        b = await process_listing(
            _raw(
                external_id="b",
                bedrooms=2,
                title="Depto 2D otro edificio Ñuñoa",
            ),
            **repos,
        )
        await session.commit()

        assert a.property_id != b.property_id

    async def test_properties_table_not_duplicated(self, session: AsyncSession, repos):
        await process_listing(_raw(external_id="a"), **repos)
        await process_listing(
            _raw(
                external_id="b",
                source="portalinmobiliario",
                title="Depto mismo inmueble otro aviso",
            ),
            **repos,
        )
        await session.commit()

        properties = (await session.execute(select(PropertyORM))).scalars().all()
        assert len(properties) == 1


# ─────────────────────────────────────────────────────────
#  Deduplicación por fingerprint
# ─────────────────────────────────────────────────────────
class TestDeduplication:
    async def test_re_ingest_updates_existing_listing(
        self, session: AsyncSession, repos
    ):
        first = await process_listing(_raw(), **repos)
        await session.commit()

        second = await process_listing(_raw(), **repos)
        await session.commit()

        assert second.id == first.id  # mismo listing actualizado

    async def test_re_ingest_updates_last_seen_at(self, session: AsyncSession, repos):
        first_seen = datetime(2026, 4, 20, tzinfo=UTC)
        second_seen = first_seen + timedelta(days=3)
        first = await process_listing(_raw(scraped_at=first_seen), **repos)
        await session.commit()

        updated = await process_listing(_raw(scraped_at=second_seen), **repos)
        await session.commit()

        assert updated.id == first.id
        assert updated.last_seen_at == second_seen
        stored = await repos["listing_repo"].find_by_id(first.id)
        assert stored is not None
        assert stored.last_seen_at == second_seen.replace(tzinfo=None)

    async def test_price_change_updates_listing(self, session: AsyncSession, repos):
        first = await process_listing(_raw(price_clp=180_000_000), **repos)
        await session.commit()

        updated = await process_listing(_raw(price_clp=170_000_000), **repos)
        await session.commit()

        assert updated.id == first.id
        assert updated.price.clp == Decimal(170_000_000)

    async def test_re_ingest_reactivates_if_was_removed(
        self, session: AsyncSession, repos
    ):
        first = await process_listing(_raw(), **repos)
        first.status = "removed"
        await repos["listing_repo"].save(first)
        await session.commit()

        reingested = await process_listing(_raw(), **repos)
        await session.commit()

        assert reingested.status == "active"

    async def test_source_external_id_wins_when_fingerprint_changes(self, session: AsyncSession, repos):
        first = await process_listing(
            _raw(external_id="stable-ext", title="Departamento amplio Ñuñoa", comuna="Ñuñoa"),
            **repos,
        )
        await session.commit()
        original_fingerprint = first.fingerprint

        updated = await process_listing(
            _raw(
                external_id="stable-ext",
                title="Departamento amplio Las Condes",
                comuna="Las Condes",
                m2=82,
            ),
            **repos,
        )
        await session.commit()

        assert updated.id == first.id
        assert updated.comuna == "las_condes"
        assert updated.m2 == 82
        assert updated.fingerprint != original_fingerprint

    async def test_comuna_change_with_same_external_id_does_not_duplicate(
        self, session: AsyncSession, repos
    ):
        first = await process_listing(_raw(external_id="same-ext", title="Depto Ñuñoa"), **repos)
        await session.commit()

        second = await process_listing(
            _raw(external_id="same-ext", title="Depto Providencia", comuna="Providencia"),
            **repos,
        )
        await session.commit()

        assert second.id == first.id
        assert second.comuna == "providencia"

    async def test_different_source_external_id_keeps_fingerprint_dedup_behavior(
        self, session: AsyncSession, repos
    ):
        first = await process_listing(_raw(external_id="one"), **repos)
        await session.commit()

        second = await process_listing(_raw(external_id="two"), **repos)
        await session.commit()

        assert second.id == first.id

    async def test_source_external_id_update_keeps_old_fingerprint_on_collision(
        self, session: AsyncSession, repos
    ):
        existing = await process_listing(
            _raw(
                external_id="same-ext",
                title="Departamento amplio",
                comuna="Marte",
            ),
            **repos,
            allow_incomplete=True,
        )
        await session.commit()
        original_fingerprint = existing.fingerprint

        owner = await process_listing(
            _raw(
                external_id="fingerprint-owner",
                title="Departamento en San Joaquín",
                comuna="San Joaquín",
                url="https://yapo.cl/owner",
            ),
            **repos,
            allow_incomplete=True,
        )
        await session.commit()

        updated = await process_listing(
            _raw(
                external_id="same-ext",
                title="Departamento en San Joaquín",
                comuna="Región Metropolitana",
            ),
            **repos,
            allow_incomplete=True,
        )
        await session.commit()

        assert updated.id == existing.id
        assert updated.comuna == "san_joaquin"
        assert updated.fingerprint == original_fingerprint
        assert "data_quality_warnings" not in updated.raw_metadata
        assert owner.fingerprint != original_fingerprint

    async def test_exact_location_is_not_degraded_to_comuna(self, session: AsyncSession, repos):
        first = await process_listing(
            _raw(
                external_id="geo-exact",
                geocode_precision="exact",
                lat=-33.401,
                lon=-70.601,
            ),
            **repos,
        )
        await session.commit()

        updated = await process_listing(
            _raw(
                external_id="geo-exact",
                geocode_precision="comuna",
                lat=-33.450,
                lon=-70.660,
            ),
            **repos,
        )
        await session.commit()

        assert updated.geocode_precision == "address"
        assert updated.coordinates == first.coordinates

    async def test_address_location_is_not_degraded_to_unknown(self, session: AsyncSession, repos):
        first = await process_listing(
            _raw(
                external_id="geo-address",
                geocode_precision="address",
                lat=-33.402,
                lon=-70.602,
            ),
            **repos,
        )
        await session.commit()

        updated = await process_listing(
            _raw(
                external_id="geo-address",
                geocode_precision="unknown",
                lat=None,
                lon=None,
            ),
            **repos,
        )
        await session.commit()

        assert updated.geocode_precision == "address"
        assert updated.coordinates == first.coordinates

    async def test_stale_weak_location_hint_is_removed_when_falling_back_to_comuna(
        self,
        session: AsyncSession,
        repos,
    ):
        await process_listing(
            _raw(
                external_id="geo-stale-hint",
                geocode_precision="address",
                raw_metadata={
                    "address_label": "cuenta y orientacion poniente",
                    "street_hint": "cuenta y orientacion poniente",
                    "geocode_precision_reason": "card_text",
                },
                lat=None,
                lon=None,
            ),
            **repos,
        )
        await session.commit()

        updated = await process_listing(
            _raw(
                external_id="geo-stale-hint",
                geocode_precision="comuna",
                raw_metadata={"geocode_precision_reason": "location_text_only"},
                lat=None,
                lon=None,
            ),
            **repos,
        )
        await session.commit()

        assert updated.geocode_precision == "comuna"
        assert "address_label" not in updated.raw_metadata
        assert "street_hint" not in updated.raw_metadata

    @pytest.mark.parametrize(
        ("new_precision", "expected_precision"),
        [("comuna", "comuna_centroid"), ("address", "address"), ("exact", "address")],
    )
    async def test_unknown_location_improves_to_better_precision(
        self,
        session: AsyncSession,
        repos,
        new_precision: str,
        expected_precision: str,
    ):
        await process_listing(
            _raw(
                external_id=f"geo-improves-{new_precision}",
                geocode_precision="unknown",
                lat=None,
                lon=None,
            ),
            **repos,
        )
        await session.commit()

        updated = await process_listing(
            _raw(
                external_id=f"geo-improves-{new_precision}",
                geocode_precision=new_precision,
                lat=-33.410,
                lon=-70.610,
            ),
            **repos,
        )
        await session.commit()

        assert updated.geocode_precision == expected_precision
        assert updated.coordinates is not None


# ─────────────────────────────────────────────────────────
#  Historial de precios
# ─────────────────────────────────────────────────────────
class TestPriceHistory:
    async def test_new_listing_records_initial_price(
        self, session: AsyncSession, repos
    ):
        observed_at = datetime(2026, 4, 20, tzinfo=UTC)
        listing = await process_listing(
            _raw(price_clp=180_000_000, scraped_at=observed_at), **repos
        )
        await session.commit()

        history = (
            (await session.execute(select(PriceHistoryORM).order_by(PriceHistoryORM.id)))
            .scalars()
            .all()
        )
        assert len(history) == 1
        assert history[0].listing_id == listing.id
        assert history[0].price_clp == Decimal(180_000_000)
        assert history[0].price_clp_snapshot == Decimal(180_000_000)
        assert history[0].change_basis == "legacy_initial"
        assert history[0].observed_at.replace(tzinfo=None) == observed_at.replace(tzinfo=None)

    async def test_new_uf_listing_records_canonical_price_history(
        self, session: AsyncSession, repos
    ):
        listing = await process_listing(
            _raw(
                external_id="uf-initial",
                price_clp=132_259_985,
                price_uf=3250,
                raw_metadata={
                    "currency_original": "UF",
                    "price_uf": 3250,
                    "uf_rate_used": "40695.38",
                },
            ),
            **repos,
        )
        await session.commit()

        history = (
            (await session.execute(select(PriceHistoryORM).order_by(PriceHistoryORM.id)))
            .scalars()
            .all()
        )
        assert listing.price_uf == Decimal("3250.00")
        assert listing.price_currency == "UF"
        assert history[0].price_uf == Decimal("3250.00")
        assert history[0].price_clp_snapshot == Decimal(132_259_985)
        assert history[0].price_currency == "UF"
        assert history[0].uf_rate_used == Decimal("40695.38")
        assert history[0].change_basis == "uf_initial"

    async def test_price_change_records_snapshot(
        self, session: AsyncSession, repos
    ):
        original_time = datetime(2026, 4, 20, tzinfo=UTC)
        await process_listing(
            _raw(price_clp=180_000_000, scraped_at=original_time), **repos
        )
        await session.commit()

        await process_listing(
            _raw(
                price_clp=170_000_000,
                scraped_at=original_time + timedelta(days=3),
            ),
            **repos,
        )
        await session.commit()

        history = (
            (await session.execute(select(PriceHistoryORM).order_by(PriceHistoryORM.id)))
            .scalars()
            .all()
        )
        assert len(history) == 2
        assert history[0].price_clp == Decimal(180_000_000)  # precio INICIAL
        assert history[1].price_clp == Decimal(180_000_000)  # precio ANTERIOR
        assert history[1].change_basis == "clp_legacy"

    async def test_price_change_with_same_external_id_and_new_fingerprint_records_snapshot(
        self, session: AsyncSession, repos
    ):
        first = await process_listing(
            _raw(
                external_id="price-stable-ext",
                title="Departamento amplio Ñuñoa",
                price_clp=180_000_000,
            ),
            **repos,
        )
        await session.commit()

        updated = await process_listing(
            _raw(
                external_id="price-stable-ext",
                title="Departamento amplio Las Condes",
                comuna="Las Condes",
                price_clp=170_000_000,
            ),
            **repos,
        )
        await session.commit()

        history = (
            (await session.execute(select(PriceHistoryORM).order_by(PriceHistoryORM.id)))
            .scalars()
            .all()
        )
        assert updated.id == first.id
        assert updated.price.clp == Decimal(170_000_000)
        assert len(history) == 2
        assert history[0].price_clp == Decimal(180_000_000)
        assert history[1].price_clp == Decimal(180_000_000)

    async def test_same_price_does_not_duplicate_initial_history(self, session: AsyncSession, repos):
        first = await process_listing(_raw(price_clp=180_000_000), **repos)
        await session.commit()
        second = await process_listing(_raw(price_clp=180_000_000), **repos)
        await session.commit()

        history = (
            (await session.execute(select(PriceHistoryORM).order_by(PriceHistoryORM.id)))
            .scalars()
            .all()
        )
        assert second.id == first.id
        assert len(history) == 1
        assert history[0].price_clp == Decimal(180_000_000)

    async def test_multiple_price_changes_accumulate(
        self, session: AsyncSession, repos
    ):
        prices = [180_000_000, 175_000_000, 170_000_000, 165_000_000]
        for i, p in enumerate(prices):
            await process_listing(
                _raw(
                    price_clp=p,
                    scraped_at=datetime(2026, 4, 20, tzinfo=UTC)
                    + timedelta(days=i),
                ),
                **repos,
            )
            await session.commit()

        history = (
            (await session.execute(select(PriceHistoryORM).order_by(PriceHistoryORM.id)))
            .scalars()
            .all()
        )
        assert len(history) == len(prices)  # precio inicial + 3 transiciones
        assert [int(row.price_clp) for row in history[1:]] == prices[:-1]

    async def test_uf_rate_only_change_does_not_create_price_history(
        self, session: AsyncSession, repos
    ):
        original_time = datetime(2026, 4, 20, tzinfo=UTC)
        await process_listing(
            _raw(
                external_id="uf-rate-only",
                price_clp=132_259_985,
                price_uf=3250,
                scraped_at=original_time,
                raw_metadata={
                    "currency_original": "UF",
                    "price_uf": 3250,
                    "uf_rate_used": "40695.38",
                },
            ),
            **repos,
        )
        await session.commit()

        updated = await process_listing(
            _raw(
                external_id="uf-rate-only",
                price_clp=120_250_000,
                price_uf=3250,
                scraped_at=original_time + timedelta(days=3),
                raw_metadata={
                    "currency_original": "UF",
                    "price_uf": 3250,
                    "uf_rate_used": "37000",
                },
            ),
            **repos,
        )
        await session.commit()

        history = (
            (await session.execute(select(PriceHistoryORM).order_by(PriceHistoryORM.id)))
            .scalars()
            .all()
        )
        assert updated.price_uf == Decimal("3250.00")
        assert updated.price.clp == Decimal(120_250_000)
        assert len(history) == 1

    async def test_uf_change_records_previous_uf_snapshot(
        self, session: AsyncSession, repos
    ):
        original_time = datetime(2026, 4, 20, tzinfo=UTC)
        await process_listing(
            _raw(
                external_id="uf-real-change",
                price_clp=120_250_000,
                price_uf=3250,
                scraped_at=original_time,
                raw_metadata={
                    "currency_original": "UF",
                    "price_uf": 3250,
                    "uf_rate_used": "37000",
                },
            ),
            **repos,
        )
        await session.commit()

        await process_listing(
            _raw(
                external_id="uf-real-change",
                price_clp=118_400_000,
                price_uf=3200,
                scraped_at=original_time + timedelta(days=3),
                raw_metadata={
                    "currency_original": "UF",
                    "price_uf": 3200,
                    "uf_rate_used": "37000",
                },
            ),
            **repos,
        )
        await session.commit()

        history = (
            (await session.execute(select(PriceHistoryORM).order_by(PriceHistoryORM.id)))
            .scalars()
            .all()
        )
        assert len(history) == 2
        assert history[1].price_clp == Decimal(120_250_000)
        assert history[1].price_clp_snapshot == Decimal(120_250_000)
        assert history[1].price_uf == Decimal("3250.00")
        assert history[1].price_currency == "UF"
        assert history[1].uf_rate_used == Decimal("37000.00")
        assert history[1].change_basis == "uf"


# ─────────────────────────────────────────────────────────
#  Validación
# ─────────────────────────────────────────────────────────
class TestValidation:
    async def test_invalid_data_does_not_persist(
        self, session: AsyncSession, repos
    ):
        with pytest.raises(ValidationError):
            await process_listing(_raw(price_clp=1_000_000), **repos)  # < MIN
        await session.rollback()

        count = await repos["listing_repo"].count_active()
        assert count == 0
        history = (await session.execute(select(PriceHistoryORM))).scalars().all()
        assert history == []

    async def test_unknown_comuna_raises(self, session: AsyncSession, repos):
        with pytest.raises(UnknownComunaError):
            await process_listing(_raw(title="Departamento amplio", comuna="Marte"), **repos)
        await session.rollback()

    async def test_missing_required_field_raises(
        self, session: AsyncSession, repos
    ):
        raw = _raw()
        del raw["title"]
        with pytest.raises(ValidationError):
            await process_listing(raw, **repos)
        await session.rollback()
