"""Synthetic roles only. Exact target resolution, valuation and release regression."""

import json
import sqlite3

import httpx
import pytest
from fastapi import FastAPI

from api.v1 import tasar, valuations
from services.sii.address_details import address_details
from services.sii.closing_opinion import build_opinion
from tests.unit.test_sii_tasar import client
from tests.unit.test_sii_tasar import data as data
from tests.unit.test_sii_tasar import release_router as release_router


@pytest.fixture
def role_data(data):
    with sqlite3.connect(data / "address-index.sqlite") as db:
        db.execute("UPDATE role SET rol='15105-900001-1' WHERE rol='subject-high'")
    return data


@pytest.mark.parametrize(
    "rol",
    ["900001-1", "00900001-0001", "15105-900001-1", "900001 / 1", "900001" + chr(0x2013) + "1"],
)
def test_role_formats_identify_same_unit(role_data, rol):
    body = address_details(rol=rol, comuna="nunoa", data_dir=str(role_data))
    assert body["status"] == "resolved"
    assert body["fields"]["closed_area_m2"] == 60
    assert body["subject_address"] == "CALLE PRUEBA 100 DP 101"
    assert body["candidates"] == []


@pytest.mark.parametrize("rol", ["", "0-1", "1-0", "bad", "1-2-3-4", "15160-900001-1", "999999-1"])
def test_invalid_missing_or_other_commune_never_chooses_unit(role_data, rol):
    body = address_details(rol=rol, comuna="nunoa", data_dir=str(role_data))
    assert body["status"] == "unavailable"
    assert body["fields"] == {}
    assert "subject_address" not in body


@pytest.mark.asyncio
async def test_role_endpoint_and_full_valuation_match_address(role_data, monkeypatch):
    monkeypatch.setenv("sii_closing_layer", "true")
    async with client(valuations.router) as api:
        details = await api.post(
            "/api/v1/tasar/rol-details", json={"rol": "900001-1", "comuna": "nunoa"}
        )
        address = await api.post(
            "/api/v1/valuations",
            json={
                "comuna": "nunoa",
                "property_type": "apartment",
                "m2": 75,
                "address": "CALLE PRUEBA 100 DP 101",
            },
        )
        role = await api.post(
            "/api/v1/valuations",
            json={"comuna": "nunoa", "property_type": "apartment", "m2": 75, "sii_rol": "900001-1"},
        )
    assert details.status_code == address.status_code == role.status_code == 200
    assert details.json()["fields"]["closed_area_m2"] == 60
    assert role.content == address.content
    assert role.json()["sii_closing_opinion"]["confidence_label"] == "Confianza alta"
    assert "15105-900001-1" not in role.text
    assert "PRUEBA" not in role.text


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", ["900001-1", {"bad": 1}, 123, "x" * 1000])
async def test_role_ignored_off_exact_release_bytes(release_router, monkeypatch, rol):
    monkeypatch.delenv("sii_closing_layer", raising=False)

    def forbidden(**kwargs):
        pytest.fail("Inactive SII layer executed")

    monkeypatch.setattr("services.sii.closing_opinion.build_opinion", forbidden)
    payload = {"comuna": "nunoa", "property_type": "apartment", "m2": 75, "sii_rol": rol}
    async with client(release_router) as old, client(valuations.router) as current:
        before = await old.post("/api/v1/valuations", json=payload)
        after = await current.post("/api/v1/valuations", json=payload)
    assert before.status_code == after.status_code == 200
    assert before.content == after.content


def test_exact_role_resolves_when_address_is_ambiguous(role_data):
    with sqlite3.connect(role_data / "address-index.sqlite") as db:
        db.execute(
            "INSERT INTO role SELECT 'other-subject',comuna,900099,street,number,unit,tower,raw,kind,year,area,source FROM role WHERE rol='15105-900001-1'"
        )
    args = {"comuna": "nunoa", "property_type": "apartment", "area": 60, "data_dir": str(role_data)}
    assert build_opinion(address="CALLE PRUEBA 100 DP 101", **args)["status"] == "ambiguous"
    assert build_opinion(address="", rol="900001-1", **args)["status"] == "available"


def test_subjects_previous_sales_still_excluded_by_role(role_data):
    rows = json.loads((role_data / "closings.json").read_text())
    own = {
        **rows[0],
        "rol": "15105-900001-1",
        "raw_id": "own-sale",
        "uf": 999999,
        "date": "2026-01-01",
    }
    (role_data / "closings.json").write_text(json.dumps([own, *rows]), encoding="utf8")
    opinion = build_opinion(
        address="",
        rol="900001-1",
        comuna="nunoa",
        property_type="apartment",
        area=60,
        data_dir=str(role_data),
    )
    assert opinion["status"] == "available" and opinion["comparable_count"] == 10
    assert "2026-01-01" not in opinion["closing_dates"]


@pytest.mark.asyncio
async def test_lookup_off_never_reads_index(monkeypatch):
    monkeypatch.delenv("sii_closing_layer", raising=False)

    def forbidden(**kwargs):
        pytest.fail("Flag off read the index")

    monkeypatch.setattr("services.sii.address_details.address_details", forbidden)
    async with client(valuations.router) as api:
        response = await api.post(
            "/api/v1/tasar/rol-details", json={"rol": "900001-1", "comuna": "nunoa"}
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_lookup_requires_auth(monkeypatch):
    monkeypatch.setenv("sii_closing_layer", "true")
    app = FastAPI()
    app.include_router(tasar.router, prefix="/api/v1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as api:
        response = await api.post(
            "/api/v1/tasar/rol-details", json={"rol": "900001-1", "comuna": "nunoa"}
        )
    assert response.status_code == 401
