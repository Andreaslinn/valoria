from copy import deepcopy
import pytest
from services.v2_contract import REQUIRED_FIELDS, check_v2_contract, v2_capabilities


def fixture():
    return {"components": {"schemas": {name: {"properties": dict.fromkeys(fields, {})}
            for name, fields in REQUIRED_FIELDS.items()}}, "paths": {
            "/api/v1/listings/analyze-url": {"post": {}},
            "/api/v1/watchlist/{listing_id}/status": {"get": {}}}}


def test_complete_contract():
    assert check_v2_contract(fixture(), v2_capabilities()) == []


def test_actual_candidate_openapi_satisfies_v2_contract():
    from api.main import create_app
    assert check_v2_contract(create_app().openapi(), v2_capabilities()) == []


@pytest.mark.parametrize("model,field", [(m, f) for m, fields in REQUIRED_FIELDS.items() for f in fields])
def test_every_critical_field_is_required(model, field):
    schema = deepcopy(fixture())
    del schema["components"]["schemas"][model]["properties"][field]
    assert f"{model}.{field} missing" in check_v2_contract(schema, v2_capabilities())


def test_missing_portal_and_identity_fail():
    assert check_v2_contract(fixture(), {}) == ["Portal URL analysis capability missing", "Deployment code fingerprint missing"]
