from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from core.entities.listing import Listing
from core.exceptions import UFServiceError
from core.ports.listing_repo import ListingRepository
from core.ports.uf_service import UFService
from services.radar import RadarService
from services.valuation import ValuationInput, ValuationService
from tests.unit.factories import make_listing


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROHIBITED_RUNTIME_PATHS = (
    "api",
    "core",
    "domain",
    "infrastructure",
    "services",
    "workers",
)
ALLOWED_RUNTIME_FILES = {
    "config/constants.py",
    "services/uf_rate.py",
}


def test_no_operational_runtime_path_uses_legacy_uf_artifact_rate() -> None:
    offenders: list[str] = []
    for dirname in PROHIBITED_RUNTIME_PATHS:
        for path in (PROJECT_ROOT / dirname).rglob("*.py"):
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            if rel in ALLOWED_RUNTIME_FILES:
                continue
            text = path.read_text(encoding="utf-8")
            if "UF_TO_CLP_FALLBACK" in text or "LEGACY_UF_ARTIFACT_RATE" in text or "37000" in text:
                offenders.append(rel)

    assert offenders == []


def test_canonical_benchmark_has_no_hardcoded_uf_rate_argument() -> None:
    from scripts.audit_valuation_canonical_price import parse_args

    args = parse_args([])

    assert not hasattr(args, "uf_rate")


async def test_canonical_benchmark_aborts_without_real_uf(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.audit_valuation_canonical_price as audit_script

    async def _fail_uf():
        raise UFServiceError("UF real no disponible")

    async def _should_not_load(*, limit):
        raise AssertionError("benchmark should abort before loading listings")

    monkeypatch.setattr(audit_script, "_resolve_real_uf_rate", _fail_uf)
    monkeypatch.setattr(audit_script, "_load_active_listings", _should_not_load)
    monkeypatch.setattr(audit_script.sys, "argv", ["audit_valuation_canonical_price.py"])

    assert await audit_script.main() == 2


async def test_valuation_service_rejects_legacy_artifact_rate() -> None:
    listings = [make_listing(fingerprint=f"v{i}", comuna="nunoa", property_type="apartment") for i in range(5)]
    service = ValuationService(
        listing_repo=_FakeListingRepository(listings),
        uf_service=_LegacyArtifactUFService(),
    )

    with pytest.raises(UFServiceError, match="37000"):
        await service.valuate_property(
            ValuationInput(
                comuna="nunoa",
                property_type="apartment",
                m2=75,
                built_area_m2=75,
                dormitorios=3,
                banos=2,
                estacionamientos=1,
            )
        )


async def test_radar_service_rejects_legacy_artifact_rate() -> None:
    listings = [make_listing(fingerprint=f"r{i}", comuna="nunoa", property_type="apartment") for i in range(12)]
    service = RadarService(
        listing_repo=_FakeListingRepository(listings),
        uf_service=_LegacyArtifactUFService(),
    )

    with pytest.raises(UFServiceError, match="37000"):
        await service.opportunities(limit=5)


class _LegacyArtifactUFService(UFService):
    async def get_current_rate(self) -> Decimal:
        return Decimal("37000")


class _FakeListingRepository(ListingRepository):
    def __init__(self, listings: list[Listing]) -> None:
        self._listings = list(listings)

    async def save(self, listing: Listing) -> Listing:
        return listing

    async def find_by_id(self, listing_id: int) -> Listing | None:
        return next((item for item in self._listings if item.id == listing_id), None)

    async def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        comuna: str | None = None,
        status: str | None = None,
    ):
        rows = self._listings
        if comuna is not None:
            rows = [item for item in rows if item.comuna == comuna]
        if status is not None:
            rows = [item for item in rows if item.status == status]
        return rows[offset : offset + limit]

    async def list_active(self, *, limit: int | None = None):
        rows = [item for item in self._listings if item.is_active]
        return rows[:limit] if limit is not None else rows

    async def find_by_fingerprint(self, fingerprint: str) -> Listing | None:
        return next((item for item in self._listings if item.fingerprint == fingerprint), None)

    async def find_by_source_external_id(self, source: str, external_id: str) -> Listing | None:
        return next(
            (
                item
                for item in self._listings
                if item.source == source and item.external_id == external_id
            ),
            None,
        )

    async def find_active_in_comuna(self, comuna_slug: str, *, property_type: str | None = None):
        rows = [item for item in self._listings if item.is_active and item.comuna == comuna_slug]
        if property_type is not None:
            rows = [item for item in rows if item.property_type == property_type]
        return rows

    async def count_active(self) -> int:
        return len([item for item in self._listings if item.is_active])
