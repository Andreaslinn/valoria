from datetime import date
from decimal import Decimal

import pytest

from services.sii.geocoding import interpolate
from services.sii.parsing import (
    address,
    catastro_row,
    comuna,
    dates,
    day,
    decimal,
    fields,
    property_type,
)
from services.sii.settings import enabled, local_url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@oracle.example:55432/valoria_sii_local",
        "postgresql+psycopg://u:p@127.0.0.1:5432/valoria_sii_local",
        "postgresql+psycopg://u:p@127.0.0.1:55432/production",
        "postgresql+psycopg://u:p@127.0.0.1:55432/valoria_sii_local?host=oracle.example",
        "postgresql://u:p@127.0.0.1:55432/valoria_sii_local",
    ],
)
def test_rejects_every_nonlocal_or_ambiguous_target(url):
    with pytest.raises(ValueError):
        local_url(url)


def test_disabled_does_not_resolve_database_or_start_job(monkeypatch, capsys):
    import sys

    from scripts.sii_ingest import main

    monkeypatch.setenv("SII_INGEST_ENABLED", "false")
    monkeypatch.setenv("SII_DATABASE_URL", "invalid")
    monkeypatch.setattr(sys, "argv", ["sii_ingest", "sii_f2890_fetch"])
    assert not enabled()
    main()
    assert '"status": "disabled"' in capsys.readouterr().out


def test_layout_rejects_missing_and_extra_columns():
    assert len(fields("|".join(["0"] * 19) + "|\r\n", 19)) == 19
    with pytest.raises(ValueError, match="layout_mismatch"):
        fields("|".join(["0"] * 18), 19)
    with pytest.raises(ValueError, match="layout_mismatch"):
        fields("|".join(["0"] * 20), 19)


def test_santiago_sector_identity_survives_filename_scope():
    raw = "13134|1|1|CALLE 123 DP 4|1000|10|H|0|0|0|0|0|0|0|100|U|0|0|0|\n"
    parsed = catastro_row(raw, "N", 13101, 7)
    assert parsed[1:4] == (13134, 1, 1)
    assert comuna("SANTIAGO CENTRO") == 13101
    assert comuna("SANTIAGO OESTE") == 13134
    assert comuna("SANTIAGO SUR") == 13135
    with pytest.raises(ValueError, match="commune_mismatch"):
        catastro_row(raw, "N", 15108, 7)


def test_surface_is_integer_m2_and_open_condition_is_ca():
    row = catastro_row("15108|100|1|2|B|2|2020|000000012|H|CA|3|\n", "NL", 15108, 4)
    assert row[8:11] == (2020, 12, True)


def test_address_street_with_number_and_explicit_dp_token():
    assert address("11 SEPTIEMBRE 123 DP 42") == ("11 SEPTIEMBRE", "123", "42")
    assert property_type("H", "CALLE 123 DP 42") == "depto"
    assert property_type("H", "CALLE 123 DP 42 BOD 1") == "depto"
    assert property_type("H", "CALLE 123 DPA 42") == "casa"
    assert property_type("Z", "CALLE 123") == "estac"
    assert property_type("L", "CALLE 123") == "bodega"


def test_exact_amount_and_dates():
    assert decimal("123,45") == Decimal("123.45")
    assert decimal("") is None
    assert day("20260201") == date(2026, 2, 1)
    with pytest.raises(ValueError):
        decimal("NaN")
    assert dates("20260102", "21210") == (date(2026, 1, 2), None, ["fe_invalida"])


def test_interpolation_requires_bracket_parity_and_local_distance():
    anchors = {100: (-33.4, -70.6), 200: (-33.4005, -70.6)}
    assert interpolate(150, anchors)[:2] == pytest.approx((-33.40025, -70.6))
    assert interpolate(151, anchors) is None
    assert interpolate(50, anchors) is None
    assert interpolate(150, {100: (-33.4, -70.6), 200: (-33.5, -70.6)}) is None


async def test_health_flag_off_preserves_original_payload(monkeypatch):
    from api.main import create_app
    from api.v1 import health as health_router

    state = {"status": "ok", "sources": {"portal": {"status": "ok"}}}

    async def fake_source():
        return state

    monkeypatch.setenv("SII_INGEST_ENABLED", "false")
    monkeypatch.setenv("SII_DATABASE_URL", "invalid")
    monkeypatch.setattr(health_router, "source_health", fake_source)
    app = create_app()
    endpoint = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/health")
    assert await endpoint() == {
        "status": "ok",
        "liveness": "ok",
        "ingestion": state,
        "sources": state["sources"],
    }
