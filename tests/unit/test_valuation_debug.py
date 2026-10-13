import json
import re
from dataclasses import replace
from decimal import Decimal

import pytest

from domain.valuation.engines.contracts import EngineComparable, EngineResult
from services.reports import build_property_valuation_report_html
from services.valuation import ValuationInput, ValuationService
from services.valuation_debug import comparable_identity, engine_trace, runtime_provenance
from tests.unit.factories import make_listing
from tests.unit.test_valuation_service import FakeListingRepository, FakeUFService


def test_ids_hash_is_order_independent_but_preserves_membership_and_missing_ids():
    a = comparable_identity([3, 1, None, 2])
    b = comparable_identity([2, 3, 1, None])
    assert a == b
    assert a["n_comparables_weighted"] == 4
    assert a["comparable_ids_missing_n"] == 1
    assert a["comparable_ids_sha256"] != comparable_identity([1, 2, 4, None])["comparable_ids_sha256"]
    assert a["comparable_ids_sha256"] != comparable_identity([1, 2, 3, 3])["comparable_ids_sha256"]


def test_runtime_provenance_does_not_invent_a_commit(monkeypatch):
    monkeypatch.delenv("VALORIA_RELEASE_COMMIT", raising=False)
    unknown = runtime_provenance()
    assert unknown["engine_commit"] is None
    assert len(unknown["runtime_source_sha256"]) == 64
    monkeypatch.setenv("VALORIA_RELEASE_COMMIT", "a" * 40)
    assert runtime_provenance()["engine_commit"] == "a" * 40
    monkeypatch.setenv("VALORIA_RELEASE_COMMIT", "not-a-commit")
    assert runtime_provenance()["engine_commit"] is None


def test_engine_trace_reports_surface_values_without_changing_engine_result():
    result = EngineResult(
        engine_name="comparables_canonical_outliers", engine_version="test_v1", status="ok",
        estimated_price_clp=220000000, estimated_price_uf=5500,
        diagnostics={"result": {"base_estimated_price_clp": 200000000, "surface_adjustment": {"applied": True}}},
        selected_comparables=(EngineComparable(7, "fp7", .9), EngineComparable(5, "fp5", .8)),
    )
    before = result.to_dict()
    trace = engine_trace(result, uf_to_clp=Decimal("40000"), area_m2=100)
    assert trace["engine_selected"] == result.engine_name
    assert trace["engine_version"] == "test_v1"
    assert trace["ppm2_base"] == 50
    assert trace["ppm2_after_surface"] == 55
    assert trace["price_surface_factor"] == 1.1
    assert trace["n_comparables_weighted"] == 2
    assert trace["comparable_ids"] == [5, 7]
    assert result.to_dict() == before


def test_consensus_trace_does_not_claim_a_single_weighted_listing_sample():
    result = EngineResult(engine_name="valoria_consensus_v1", engine_version="v1", status="ok", estimated_price_clp=200000000)
    trace = engine_trace(result, uf_to_clp=Decimal("40000"), area_m2=100)
    assert trace["ppm2_final"] == 50
    assert trace["ppm2_base"] is None
    assert trace["ppm2_after_surface"] is None
    assert trace["price_surface_factor"] is None
    assert trace["n_comparables_weighted"] is None
    assert trace["comparable_ids_sha256"] is None


def test_trace_does_not_invent_ids_for_engines_that_do_not_expose_them():
    result = EngineResult(engine_name="hedonic_baseline_v1", engine_version="v1", status="success", comparables_used=50)
    trace = engine_trace(result, uf_to_clp=Decimal("40000"), area_m2=100)
    assert trace["n_comparables_weighted"] is None
    assert trace["comparable_ids_sha256"] is None
    assert trace["n_comparables_reported"] == 50


def test_missing_source_files_are_reported_without_failing_valuation(monkeypatch, tmp_path):
    monkeypatch.setattr("services.valuation_debug._ROOT", tmp_path)
    assert all(value is None for value in runtime_provenance()["runtime_files_sha256"].values())


@pytest.mark.asyncio
@pytest.mark.parametrize("consensus", [False, True])
async def test_debug_survives_service_and_report_without_changing_estimate(monkeypatch, consensus):
    monkeypatch.setenv("VALORIA_USE_CONSENSUS", str(consensus).lower())
    monkeypatch.setenv("VALUATION_QUALITY_V2_APPLY_MODE", "off")
    listings = [replace(make_listing(fingerprint=f"debug-{i}", price_currency="CLP"), id=i + 1) for i in range(8)]
    service = ValuationService(listing_repo=FakeListingRepository(listings), uf_service=FakeUFService())
    payload = ValuationInput(comuna="nunoa", property_type="apartment", m2=75)
    result = await service.valuate_property(payload)
    debug = result.to_payload()["valuation_debug"]
    assert debug["engine_selected"] == ("comparables_canonical_outliers" if consensus else "comparables_legacy")
    assert debug["n_comparables_weighted"] == 8
    assert debug["comparable_ids"] == list(range(1, 9))
    assert debug["ppm2_final"] == pytest.approx(result.estimated_price_clp / 39000 / 75)
    html = build_property_valuation_report_html(valuation_result=result.to_payload(), valuation_payload={"comuna": "nunoa", "m2": 75})
    encoded = re.search(r'id="valoria-valuation-debug">(.*?)</script>', html).group(1)
    assert json.loads(encoded) == debug


def test_report_debug_cannot_terminate_json_script():
    debug = {"engine_selected": "</script><script>alert(1)</script>"}
    html = build_property_valuation_report_html(
        valuation_result={"estimated_price_uf": 5000, "valuation_debug": debug},
        valuation_payload={"comuna": "nunoa", "m2": 75},
    )
    encoded = re.search(r'id="valoria-valuation-debug">(.*?)</script>', html).group(1)
    assert "<" not in encoded
    assert json.loads(encoded) == debug


@pytest.mark.asyncio
async def test_rejected_quality_challenger_does_not_replace_legacy_version(monkeypatch):
    monkeypatch.setenv("VALORIA_USE_CONSENSUS", "false")
    monkeypatch.setenv("VALUATION_QUALITY_V2_APPLY_MODE", "guarded")
    monkeypatch.setenv("VALUATION_QUALITY_V2_MIN_VALID_COMPARABLES", "100")
    listings = [make_listing(fingerprint=f"version-{i}", price_currency="CLP") for i in range(8)]
    service = ValuationService(listing_repo=FakeListingRepository(listings), uf_service=FakeUFService())
    result = await service.valuate_property(ValuationInput(comuna="nunoa", property_type="apartment", m2=75))
    assert result.valuation_debug["engine_selected"] == "comparables_legacy"
    assert result.valuation_debug["engine_version"] == "phase0b_legacy_v1"
