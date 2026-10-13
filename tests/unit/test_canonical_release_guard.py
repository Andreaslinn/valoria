import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from api.deps import get_valuation_service
from api.v1.valuations import ValuationRequest, valuate
from core.exceptions import InsufficientDataError
from domain.valuation.engines.contracts import EngineResult
from services.release_guard import verify_canonical_response, verify_release_tree
from services.valuation import ValuationInput
from tests.unit.factories import make_listing
from tests.unit.test_valuation_service import FakeListingRepository, FakeUFService


@pytest.fixture
def canonical_service():
    listings = [replace(make_listing(fingerprint=f"release-{i}", price_currency="UF", price_uf=Decimal(4000+i*10),
                                    price_clp=300000000, price_uf_source="scraped"), id=i+1) for i in range(8)]
    return get_valuation_service(FakeListingRepository(listings), FakeUFService())


@pytest.mark.asyncio
async def test_real_api_boundary_never_mixes_engines_or_reuses_prior_comparables(monkeypatch, canonical_service):
    def forbidden(*args, **kwargs):
        pytest.fail("Production canonical-only path executed a previous or mixed engine")
    for name in ("run_beta_consensus", "valuate_with_comparables", "run_experimental_engine_lab"):
        monkeypatch.setattr("services.valuation."+name, forbidden)
    monkeypatch.setenv("VALORIA_USE_CONSENSUS", "true")
    monkeypatch.setenv("VALORIA_EXPERIMENTAL_ENGINE_LAB_ENABLED", "true")
    response = await valuate(current_user=SimpleNamespace(id=None), payload=ValuationRequest(
        comuna="nunoa", property_type="apartment", m2=75, dormitorios=3, banos=2, estacionamientos=1,
    ), service=canonical_service, session=None)
    payload = response.model_dump()
    verify_canonical_response(payload)
    assert payload["selected_engine_names"] == ["comparables_canonical_outliers"]
    assert payload["estimated_price_uf"] == pytest.approx(4035, abs=0.01)
    assert payload["valuation_debug"]["comparable_ids"] == list(range(1,9))


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["mixed", "stale_comparables", "replaced_price"])
async def test_exit_gate_rejects_production_regressions(canonical_service, corruption):
    result = await canonical_service.valuate_property(ValuationInput(comuna="nunoa", property_type="apartment", m2=75))
    payload = deepcopy(result.to_payload())
    if corruption == "mixed":
        payload["selected_engine_names"] = ["valoria_consensus_v1"]
        payload["consensus_used"] = True
    elif corruption == "stale_comparables":
        payload["comparables"][0]["listing_id"] = 99999
    else:
        payload["estimated_price_uf"] *= 1.78
    with pytest.raises(RuntimeError):
        verify_canonical_response(payload)


@pytest.mark.asyncio
async def test_unavailable_canonical_never_falls_back(monkeypatch, canonical_service):
    monkeypatch.setattr("services.valuation.ComparablesCanonicalEngine.valuate", lambda *args: EngineResult(
        engine_name="comparables_canonical_outliers", engine_version="test", status="insufficient_data"))
    with pytest.raises(InsufficientDataError):
        await canonical_service.valuate_property(ValuationInput(comuna="nunoa", property_type="apartment", m2=75))


def test_release_manifest_detects_modified_or_inherited_source(tmp_path):
    source = tmp_path/"app.py"
    source.write_text("value=1\n",encoding="utf-8")
    (tmp_path/"release-manifest.json").write_text(json.dumps({"commit":"a"*40,"files":{
        "app.py":hashlib.sha256(source.read_bytes()).hexdigest()}}),encoding="utf-8")
    assert verify_release_tree(tmp_path)["source_tree_match"]
    source.write_text("value=2\n",encoding="utf-8")
    with pytest.raises(RuntimeError,match="drift"):
        verify_release_tree(tmp_path)
    source.write_text("value=1\n",encoding="utf-8")
    (tmp_path/"inherited.py").write_text("old_code=True\n",encoding="utf-8")
    with pytest.raises(RuntimeError,match="inherited"):
        verify_release_tree(tmp_path)
