"""Radar must consume the Tasar service result, not recreate its algorithms."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

import services.radar as radar_module
from config import get_settings
from core.entities.opportunity import Opportunity, RadarResult
from core.exceptions import InsufficientDataError, UFServiceError
from core.value_objects.price import Price
from core.value_objects.score import Score
from services.listing_analysis import _valuation_input, analyze_listing_lookup
from services.listing_url_lookup import listing_to_form_data
from services.radar import RadarService
from services.valuation import ValuationService
from tests.unit.factories import make_listing
from tests.unit.test_radar_service import _FakeListingRepo, _FakeUFService, UF


@pytest.fixture(autouse=True)
def configuration(monkeypatch):
    monkeypatch.setenv("RADAR_REQUIRE_FRESH_LISTINGS", "false")
    monkeypatch.setenv("VALORIA_USE_CONSENSUS", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def listing(lid=1130, price=1520, area=47):
    row = make_listing(fingerprint=str(lid), comuna="independencia", m2=area,
                       bedrooms=2, bathrooms=1, parking=1, price_currency="UF",
                       price_uf=price, price_clp=Decimal(price) * UF,
                       price_uf_source="scraped", price_uf_confidence="high")
    row.id = lid
    return row


def screening(monkeypatch, rows):
    raw = [Opportunity(listing=row, market_price=Price(Decimal("3404.75") * UF),
                       discount_pct=0.55, confidence=Score(0.9), comparables_used=20)
           for row in rows]
    monkeypatch.setattr(radar_module, "detect_opportunities", lambda *a, **k:
                        RadarResult(raw, len(rows), False, {"apartment": False}))


def valuation(estimate=2376.63, confidence=0.6, **changes):
    result = dict(estimated_price_uf=estimate, estimated_price_clp=int(Decimal(str(estimate)) * UF),
                  confidence_score=confidence, confidence="medium", confidence_label="medium", confidence_reasons=["test"], confidence_risk_flags=["weak_microzone"],
                  comparable_count=17, warnings=["weak_microzone"],
                  beta_scope_status="beta_supported", beta_scope_flags=[], beta_scope_message="test",
                  comparable_quality_level="acceptable", comparable_quality_flags=[],
                  valuation_strategy="consensus_v1", consensus_used=True,
                  consensus_unavailable_reason=None, fallback_engine_used=None)
    result.update(changes)
    return SimpleNamespace(**result)


class SpyTasar:
    def __init__(self, results):
        self.results = results
        self.calls = []
    async def valuate_property(self, data, *, valuation_strategy):
        self.calls.append((data, valuation_strategy))
        result = self.results[data.target_listing_id]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.asyncio
async def test_radar_calls_injected_tasar_with_identity_and_uses_its_complete_result(monkeypatch):
    row = listing(); screening(monkeypatch, [row])
    tasar = SpyTasar({1130: valuation()})
    result = (await RadarService(listing_repo=_FakeListingRepo([row]),
              uf_service=_FakeUFService(), valuation_service=tasar).opportunities())[0]
    data, strategy = tasar.calls[0]
    assert strategy == "consensus_v1"
    assert (data.target_listing_id, data.m2, data.dormitorios, data.banos, data.estacionamientos) == (1130, 47, 2, 1, 1)
    assert result.estimated_price_uf == result.estimated_value_uf == 2376.63
    assert result.discount_pct == round((1 - 1520 / 2376.63) * 100, 2)
    assert result.score == round((result.discount_pct / 100) * 0.6, 4)
    assert result.confidence_score == 0.6 and result.confidence == "medium"
    assert result.comparables_used == 17 and result.warnings == ["weak_microzone"]
    assert result.to_payload()["consensus_used"] is True


@pytest.mark.asyncio
async def test_canonical_result_rejects_false_opportunity_and_reranks_bounded_candidates(monkeypatch):
    rows = [listing(1130), listing(1131), listing(1132), listing(1133)]
    screening(monkeypatch, rows)
    tasar = SpyTasar({1130: valuation(1400), 1131: valuation(2200), 1132: valuation(2600)})
    result = await RadarService(listing_repo=_FakeListingRepo(rows), uf_service=_FakeUFService(),
                               valuation_service=tasar).opportunities(limit=3)
    assert len(tasar.calls) == 3
    assert [x.listing_id for x in result] == [1132, 1131]


@pytest.mark.asyncio
async def test_unavailable_canonical_estimate_never_falls_back_to_screening(monkeypatch):
    rows = [listing(1130), listing(1131)]; screening(monkeypatch, rows)
    tasar = SpyTasar({1130: InsufficientDataError("no data"), 1131: valuation()})
    result = await RadarService(listing_repo=_FakeListingRepo(rows), uf_service=_FakeUFService(),
                               valuation_service=tasar).opportunities()
    assert [x.listing_id for x in result] == [1131]


@pytest.mark.asyncio
async def test_real_tasar_fallback_is_preserved_and_uf_outage_is_not_hidden(monkeypatch):
    row = listing(); screening(monkeypatch, [row])
    tasar = SpyTasar({1130: valuation(consensus_used=False, valuation_strategy="current_engine_fallback",
                                    fallback_engine_used="comparables_current", consensus_unavailable_reason="one_family")})
    service = RadarService(listing_repo=_FakeListingRepo([row]), uf_service=_FakeUFService(), valuation_service=tasar)
    result = (await service.opportunities())[0]
    assert result.consensus_used is False and result.fallback_engine_used == "comparables_current"
    tasar.results[1130] = UFServiceError("UF unavailable")
    with pytest.raises(UFServiceError):
        await service.opportunities()


@pytest.mark.asyncio
async def test_actual_shared_engine_matches_tasar_and_url_analysis_with_extreme_comparable():
    target = listing()
    normal = [listing(2000 + i, 2100 + i * 25, 44 + i % 8) for i in range(25)]
    extreme = listing(6124, 23000, 49)
    repo = _FakeListingRepo([target, *normal, extreme]); uf = _FakeUFService()
    tasar = ValuationService(listing_repo=repo, uf_service=uf)
    data, missing = _valuation_input(listing_to_form_data(target)); assert not missing
    direct = await tasar.valuate_property(data, valuation_strategy="consensus_v1")
    analysis = await analyze_listing_lookup(listing_to_form_data(target), valuation_service=tasar)
    result = await RadarService(listing_repo=repo, uf_service=uf, valuation_service=tasar).opportunities(limit=20)
    radar = next(x for x in result if x.listing_id == 1130)
    assert radar.estimated_price_uf == direct.estimated_price_uf == analysis.valuation["estimated_value_uf"]
    assert radar.consensus_used == direct.consensus_used
    assert (radar.confidence_score, radar.confidence_label) == (direct.confidence_score, direct.confidence_label)
    assert 1130 not in [x.listing_id for x in direct.comparables]
    canonical = next(x for x in direct.engine_results if x.engine_name == "comparables_canonical_outliers")
    assert "id:6124" in canonical.diagnostics["exclusion_ids"]["price_m2_high_outlier"]
