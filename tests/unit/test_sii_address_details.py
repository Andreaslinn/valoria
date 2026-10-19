"""Subject facts only; never borrow room counts from a nearby listing."""

import json
import sqlite3

import httpx
import pytest
from fastapi import FastAPI

from api.v1 import tasar, valuations
from services.sii.address_details import address_details
from tests.unit.test_sii_tasar import client
from tests.unit.test_sii_tasar import data as data


@pytest.mark.asyncio
async def test_resolved_facts_without_sale_pool(data, monkeypatch):
    monkeypatch.setenv("sii_closing_layer", "true")
    (data / "closings.json").unlink()
    before = (data / "address-index.sqlite").read_bytes()
    async with client(valuations.router) as api:
        response = await api.post(
            "/api/v1/tasar/address-details",
            json={"address": "CALLE PRUEBA 100 DP 101", "comuna": "nunoa"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resolved"
    assert body["fields"] == {
        "closed_area_m2": 60.0,
        "construction_year": 2020,
        "property_type": "apartment",
    }
    assert set(body["missing_fields"]) == {"bedrooms", "bathrooms", "parking", "land_area_m2"}
    assert (data / "address-index.sqlite").read_bytes() == before
    assert not any(
        s in json.dumps(body) for s in ("subject-high", "PRUEBA", "900001", "raw_id", "rol")
    )


@pytest.mark.parametrize(
    "address,status",
    [
        ("CALLE PRUEBA 400", "ambiguous"),
        ("CALLE PRUEBA 100 DP 999", "ambiguous"),
        ("CALLE NO EXISTE 999", "unavailable"),
    ],
)
def test_no_guessing(data, address, status):
    body = address_details(address=address, comuna="nunoa", data_dir=str(data))
    assert body["status"] == status
    assert body["fields"] == {}
    assert body["message"]


def test_building_with_multiple_units_never_borrows_area(data):
    db = sqlite3.connect(data / "address-index.sqlite")
    db.execute(
        "INSERT INTO role SELECT 'subject-other',comuna,block,street,number,'102',tower,raw,kind,year,80,source FROM role WHERE rol='subject-high'"
    )
    db.commit()
    db.close()
    body = address_details(address="CALLE PRUEBA 100", comuna="nunoa", data_dir=str(data))
    assert body["status"] == "ambiguous"
    assert body["fields"] == {}
    assert body["candidate_count"] == 2


@pytest.mark.asyncio
async def test_flag_off_never_reads_catastro(monkeypatch):
    monkeypatch.delenv("sii_closing_layer", raising=False)

    def forbidden(**kwargs):
        pytest.fail("Flag off read the catastro")

    monkeypatch.setattr("services.sii.address_details.address_details", forbidden)
    async with client(valuations.router) as api:
        response = await api.post(
            "/api/v1/tasar/address-details", json={"address": "CALLE PRUEBA 100", "comuna": "nunoa"}
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_authentication_required(monkeypatch):
    monkeypatch.setenv("sii_closing_layer", "true")
    app = FastAPI()
    app.include_router(tasar.router, prefix="/api/v1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as api:
        response = await api.post(
            "/api/v1/tasar/address-details", json={"address": "CALLE PRUEBA 100", "comuna": "nunoa"}
        )
    assert response.status_code == 401


def test_non_residential_unit_does_not_fill_housing(data):
    db = sqlite3.connect(data / "address-index.sqlite")
    db.execute("UPDATE role SET kind='bodega' WHERE rol='subject-high'")
    db.commit()
    db.close()
    body = address_details(address="CALLE PRUEBA 100 DP 101", comuna="nunoa", data_dir=str(data))
    assert body["status"] == "unavailable" and body["fields"] == {}
