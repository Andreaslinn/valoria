"""Tests de integración de run_scraper_job.

Usa un FakeScraper que devuelve dicts controlados y un session_factory
contra SQLite in-memory. Verifica que cada listing corre en su propia
transacción (un fallo no tumba el batch).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from infrastructure.db.models import AlertORM, PriceHistoryORM
from infrastructure.db.repositories import SqlAlchemyListingRepository
from infrastructure.scrapers.base import ScraperBase, ScraperResult
from workers import scraper_job
from workers.scraper_job import JobStats, run_scraper_job


# ─────────────────────────────────────────────────────────
#  Fake scraper
# ─────────────────────────────────────────────────────────
class FakeScraper(ScraperBase):
    def __init__(self, results: list[ScraperResult], source_name: str = "yapo"):
        self.source_name = source_name
        self._results = results

    async def scrape(self) -> list[ScraperResult]:
        return list(self._results)


def _good(**overrides) -> ScraperResult:
    base: ScraperResult = {
        "source": "yapo",
        "external_id": "ext-1",
        "title": "Depto 3D/2B Ñuñoa",
        "comuna": "Ñuñoa",
        "m2": 75,
        "bedrooms": 3,
        "bathrooms": 2,
        "parking": 1,
        "price_clp": 180_000_000,
        "url": "https://yapo.cl/1",
        "lat": -33.4569,
        "lon": -70.5969,
        "scraped_at": datetime.now(UTC),
        "raw_metadata": {},
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


# ─────────────────────────────────────────────────────────
#  Fixture: session_factory conectado al engine de test
# ─────────────────────────────────────────────────────────
@pytest_asyncio.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# ─────────────────────────────────────────────────────────
#  Tests
# ─────────────────────────────────────────────────────────
class TestJobHappyPath:
    async def test_processes_all_valid_listings(self, session_factory):
        scraper = FakeScraper([
            _good(external_id="a", title="Depto primero Ñuñoa centro"),
            _good(external_id="b", title="Depto segundo Ñuñoa tranquilo"),
            _good(external_id="c", title="Depto tercero Ñuñoa amplio"),
        ])
        stats = await run_scraper_job(scraper, session_factory)

        assert stats.scraped == 3
        assert stats.processed == 3
        assert stats.validation_errors == 0

    async def test_data_is_persisted(self, session_factory):
        titles = ["primero", "segundo", "tercero", "cuarto", "quinto"]
        scraper = FakeScraper([
            _good(title=f"Depto {t} Ñuñoa", external_id=f"e{i}")
            for i, t in enumerate(titles)
        ])
        await run_scraper_job(scraper, session_factory)

        async with session_factory() as s:
            count = await SqlAlchemyListingRepository(s).count_active()
            assert count == 5


class TestErrorIsolation:
    async def test_validation_error_does_not_kill_batch(self, session_factory):
        scraper = FakeScraper([
            _good(external_id="ok1", title="Depto primero Ñuñoa"),
            _good(external_id="bad", title="Depto malo", price_clp=1_000_000),
            _good(external_id="ok2", title="Depto segundo Ñuñoa"),
        ])
        stats = await run_scraper_job(scraper, session_factory)

        assert stats.scraped == 3
        assert stats.processed == 2
        assert stats.validation_errors == 1

        async with session_factory() as s:
            assert await SqlAlchemyListingRepository(s).count_active() == 2
            history = (
                (await s.execute(select(PriceHistoryORM).order_by(PriceHistoryORM.id)))
                .scalars()
                .all()
            )
            assert len(history) == 2
            assert [int(row.price_clp) for row in history] == [180_000_000, 180_000_000]

    async def test_unknown_comuna_saved_as_incomplete(self, session_factory):
        scraper = FakeScraper([
            _good(
                comuna="Marte",
                title="Depto marciano amplio",
                description="Texto largo de prueba para diagnostico de comuna desconocida.",
            ),
            _good(external_id="ok", title="Depto terrícola Ñuñoa"),
        ])
        stats = await run_scraper_job(scraper, session_factory)
        assert stats.processed == 2
        assert stats.validation_errors == 0
        assert stats.incomplete_saved == 1
        assert stats.reason_counts["unknown_comuna"] == 1
        assert stats.comuna_unknown == 1
        assert len(stats.unknown_comuna_samples) == 1
        assert stats.unknown_comuna_samples[0].location_text == "Marte"
        assert stats.unknown_comuna_samples[0].description_snippet == (
            "Texto largo de prueba para diagnostico de comuna desconocida."
        )
        assert stats.unknown_comuna_samples[0].extraction_attempts


class TestJobStats:
    async def test_success_rate_computed(self, session_factory):
        scraper = FakeScraper([
            _good(external_id="a", title="Depto primero Ñuñoa"),
            _good(external_id="bad", title="Depto malo", price_clp=1_000),
        ])
        stats = await run_scraper_job(scraper, session_factory)
        assert stats.success_rate == 0.5

    async def test_success_rate_zero_on_empty(self, session_factory):
        scraper = FakeScraper([])
        stats = await run_scraper_job(scraper, session_factory)
        assert stats.scraped == 0
        assert stats.success_rate == 0.0
        assert "scraper_zero_raw_results" in stats.health_warnings
        assert "scrape" in stats.stage_durations_sec

    async def test_active_dimension_snapshots_are_recorded(self, session_factory):
        scraper = FakeScraper([_good(external_id="dim", title="Depto dimensiones Ñuñoa")])
        stats = await run_scraper_job(scraper, session_factory)

        assert stats.active_after["source"]["yapo"] == 1
        assert stats.active_after["comuna"]["nunoa"] == 1
        assert stats.active_after["property_type"]["apartment"] == 1
        assert stats.active_after["geocode_precision"]
        assert stats.duration_sec >= 0

    async def test_pipeline_preserves_explicit_house_property_type(self, session_factory):
        scraper = FakeScraper([
            _good(
                external_id="house-1",
                property_type="house",
                title="Departamento amplio en Nunoa",
                url="https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-amplio/123",
                raw_metadata={"category": "departamentos"},
            )
        ])
        stats = await run_scraper_job(scraper, session_factory)

        assert stats.processed == 1
        assert stats.active_after["property_type"]["house"] == 1

    async def test_comuna_strategy_metrics(self, session_factory):
        scraper = FakeScraper([
            _good(external_id="title", title="Depto en Ñuñoa", comuna="Marte"),
            _good(external_id="location", title="Depto amplio", comuna="stgo"),
            _good(
                external_id="description",
                title="Depto amplio",
                comuna="Región Metropolitana",
                description="Cercano a metro en San Miguel.",
            ),
            _good(external_id="outside", title="Depto amplio", comuna="Valparaíso"),
        ])
        stats = await run_scraper_job(scraper, session_factory)

        assert stats.comuna_detected_from_title == 1
        assert stats.comuna_detected_from_location == 1
        assert stats.comuna_detected_from_description == 1
        assert stats.comuna_detected_from_alias == 1
        assert stats.comuna_detected_from_partial_match == 2
        assert stats.outside_rm_candidates == 1
        assert len(stats.unknown_comuna_samples) == 1

    async def test_target_scope_metrics_are_counted(self, session_factory):
        scraper = FakeScraper([
            _good(
                external_id="general-outside",
                title="Depto Valparaíso",
                comuna="Valparaíso",
                raw_metadata={
                    "target_label": "general",
                    "target_scope": "general",
                    "target_query": "keyword.departamentos venta",
                },
            ),
            _good(
                external_id="rm-nunoa",
                title="Depto Ñuñoa",
                comuna="Ñuñoa",
                raw_metadata={
                    "target_label": "nunoa",
                    "target_scope": "rm",
                    "target_query": "keyword.departamentos venta nunoa",
                },
            ),
        ])
        stats = await run_scraper_job(scraper, session_factory)

        assert stats.general_scope_count == 1
        assert stats.rm_scope_count == 1
        assert stats.by_target["general"]["unique"] == 1
        assert stats.by_target["general"]["unknown"] == 1
        assert stats.by_target["general"]["outside_rm"] == 1
        assert stats.by_target["nunoa"]["unique"] == 1
        assert stats.by_target["nunoa"]["detected"] == 1

    async def test_unknown_comuna_samples_are_limited(self, session_factory):
        scraper = FakeScraper([
            _good(
                external_id=f"unknown-{index}",
                title=f"Depto desconocido {index}",
                comuna=f"Marte {index}",
                url=f"https://yapo.cl/{index}",
            )
            for index in range(25)
        ])
        stats = await run_scraper_job(scraper, session_factory)

        assert stats.comuna_unknown == 25
        assert len(stats.unknown_comuna_samples) == 20

    async def test_duplicate_run_is_counted_as_skipped(self, session_factory):
        scraper = FakeScraper([_good(external_id="dup", title="Depto duplicado Ñuñoa")])
        first = await run_scraper_job(scraper, session_factory)
        second = await run_scraper_job(scraper, session_factory)

        assert first.inserted == 1
        assert second.inserted == 0
        assert second.skipped == 1
        assert second.processed == 0


class TestPriceDropAlertsAreSeparated:
    async def test_scraper_job_does_not_create_price_drop_alerts(self, session_factory):
        first = FakeScraper([_good(external_id="drop", title="Depto rebaja Nunoa", price_clp=180_000_000)])
        second = FakeScraper([_good(external_id="drop", title="Depto rebaja Nunoa", price_clp=170_000_000)])

        await run_scraper_job(first, session_factory)
        stats = await run_scraper_job(second, session_factory)

        async with session_factory() as s:
            alerts = (await s.execute(select(AlertORM))).scalars().all()

        assert stats.price_drop_alerts_created == 0
        assert stats.price_drop_alerts_skipped == 0
        assert alerts == []

    async def test_no_price_drop_creates_no_alert(self, session_factory):
        scraper = FakeScraper([_good(external_id="stable", title="Depto estable Nunoa", price_clp=180_000_000)])

        stats = await run_scraper_job(scraper, session_factory)

        async with session_factory() as s:
            alerts = (await s.execute(select(AlertORM))).scalars().all()

        assert stats.price_drop_alerts_created == 0
        assert alerts == []


class TestCliEntrypoint:
    async def test_main_prints_start_and_summary(self, monkeypatch, capsys):
        async def fake_run_yapo_once(*, max_pages: int = 3):
            _ = max_pages
            return JobStats(
                source="yapo",
                scraped=2,
                inserted=1,
                updated=0,
                skipped=1,
                comuna_detected_from_title=1,
                unknown_comuna_samples=[
                    scraper_job.UnknownComunaSample(
                        source="yapo",
                        external_id="unknown",
                        title="Depto sin comuna",
                        location_text="Marte",
                        address=None,
                        description_snippet="Sin datos",
                        comuna_raw="Marte",
                        extraction_attempts=[
                            {
                                "source": "location",
                                "text": "Marte",
                                "normalized_text": "marte",
                                "match_strategy": None,
                                "match_value": None,
                            }
                        ],
                        url="https://yapo.cl/unknown",
                    )
                ],
            )

        monkeypatch.setattr(scraper_job, "run_yapo_once", fake_run_yapo_once)

        exit_code = await scraper_job.main()
        out = capsys.readouterr().out

        assert exit_code == 0
        assert "== AVM scraper job: inicio ==" in out
        assert "fuente: yapo" in out
        assert "encontrados: 2" in out
        assert "insertados: 1" in out
        assert "duplicados/saltados: 1" in out
        assert "comuna_detected_from_title: 1" in out
        assert "=== UNKNOWN COMUNA SAMPLE ===" in out
        assert "location_text: Marte" in out

    async def test_main_says_when_yapo_returns_no_results(self, monkeypatch, capsys):
        async def fake_run_yapo_once(*, max_pages: int = 3):
            _ = max_pages
            return JobStats(source="yapo", scraped=0)

        monkeypatch.setattr(scraper_job, "run_yapo_once", fake_run_yapo_once)

        exit_code = await scraper_job.main()
        out = capsys.readouterr().out

        assert exit_code == 0
        assert "Yapo no devolvio resultados" in out


class TestEndToEndWithRealScraperFixture:
    """Conecta los fixtures HTML reales + parser + pipeline completo."""

    async def test_yapo_fixture_flows_through_job(self, session_factory):
        from decimal import Decimal
        from pathlib import Path

        from infrastructure.scrapers.yapo import YapoScraper

        fixture = Path(__file__).parent.parent / "fixtures" / "yapo_list.html"
        html = fixture.read_text(encoding="utf-8")

        class FixtureScraper(ScraperBase):
            source_name = "yapo"

            async def scrape(self) -> list[ScraperResult]:
                return YapoScraper.parse_listings(html, uf_to_clp=Decimal("37000"))

        stats = await run_scraper_job(FixtureScraper(), session_factory)
        # 3 cards parseadas: Arica y Viña del Mar quedan incompletas por comuna
        # desconocida; Ñuñoa queda activa para comparables.
        assert stats.scraped == 3
        assert stats.processed == 3
        assert stats.validation_errors == 0
        assert stats.incomplete_saved == 2

        async with session_factory() as s:
            assert await SqlAlchemyListingRepository(s).count_active() == 1

    async def test_portal_fixture_flows_through_job(self, session_factory):
        from decimal import Decimal
        from pathlib import Path

        from infrastructure.scrapers.portalinmobiliario import (
            PortalInmobiliarioScraper,
        )

        fixture = Path(__file__).parent.parent / "fixtures" / "portal_list.html"
        html = fixture.read_text(encoding="utf-8")

        class FixtureScraper(ScraperBase):
            source_name = "portalinmobiliario"

            async def scrape(self) -> list[ScraperResult]:
                return PortalInmobiliarioScraper.parse_listings(
                    html, uf_to_clp=Decimal("37000")
                )

        stats = await run_scraper_job(FixtureScraper(), session_factory)
        # Ambas cards Las Condes son válidas.
        assert stats.scraped == 2
        assert stats.processed == 2

        async with session_factory() as s:
            assert await SqlAlchemyListingRepository(s).count_active() == 2
