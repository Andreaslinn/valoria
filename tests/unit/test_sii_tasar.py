"""Synthetic fixtures only; release bytes, real kNN and frozen gate at API boundary."""

import json
import sqlite3
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from api import deps
from api.v1 import tasar, valuations
from infrastructure.db.database import get_db
from services.sii.closing_address import SCHEMA
from services.sii.closing_opinion import build_opinion
from tests.unit.factories import make_listing
from tests.unit.test_valuation_service import FakeListingRepository, FakeUFService

RELEASE = "24b56dc6fe626d19834bcd6707a9b77d1d3d44c7"


@pytest.fixture(scope="module")
def release_router():
    source = subprocess.check_output(
        ["git", "show", f"{RELEASE}:api/v1/valuations.py"],
        cwd=Path(__file__).parents[2],
        encoding="utf8",
    )
    module = ModuleType("sii_release_valuation_boundary")
    sys.modules[module.__name__] = module
    exec(compile(source, "release/api/v1/valuations.py", "exec"), module.__dict__)
    return module.router


def client(router):
    listings = [
        replace(
            make_listing(
                fingerprint=f"sii-test-{i}",
                price_currency="UF",
                price_uf=Decimal(4000 + i * 10),
                price_uf_source="scraped",
            ),
            id=i + 1,
        )
        for i in range(12)
    ]
    service = deps.get_valuation_service(FakeListingRepository(listings), FakeUFService())
    app = FastAPI()
    app.dependency_overrides[deps._resolve_current_user] = lambda: SimpleNamespace(id=None)
    app.dependency_overrides[deps.get_valuation_service] = lambda: service

    async def no_database():
        yield None

    app.dependency_overrides[get_db] = no_database
    app.include_router(router, prefix="/api/v1")
    app.include_router(tasar.router, prefix="/api/v1")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def data(tmp_path, monkeypatch):
    db = sqlite3.connect(tmp_path / "address-index.sqlite")
    db.executescript(SCHEMA)
    rows = [
        (
            "subject-high",
            15105,
            900001,
            "PRUEBA",
            "100",
            "101",
            None,
            "CALLE PRUEBA 100 DP 101",
            "depto",
            2020,
            60,
            1,
        ),
        (
            "subject-ref",
            15105,
            900002,
            "PRUEBA",
            "200",
            "101",
            None,
            "CALLE PRUEBA 200 DP 101",
            "depto",
            1970,
            60,
            1,
        ),
        (
            "subject-missing",
            15105,
            900003,
            "PRUEBA",
            "300",
            "101",
            None,
            "CALLE PRUEBA 300 DP 101",
            "depto",
            None,
            60,
            1,
        ),
        (
            "subject-amb1",
            15105,
            900004,
            "PRUEBA",
            "400",
            "101",
            None,
            "CALLE PRUEBA 400 DP 101",
            "depto",
            2020,
            60,
            1,
        ),
        (
            "subject-amb2",
            15105,
            900005,
            "PRUEBA",
            "400",
            "101",
            None,
            "CALLE PRUEBA 400 DP 101",
            "depto",
            2020,
            60,
            1,
        ),
    ]
    db.executemany("INSERT INTO role VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    db.commit()
    db.close()
    closings = []
    for group, block, number, year in (("high", 900001, "100", 2020), ("ref", 900002, "200", 1970)):
        for i in range(10):
            closings.append(
                {
                    "rol": f"synthetic-comp-{group}-{i}",
                    "raw_id": f"{group}-{i}",
                    "comuna": 15105,
                    "block": block,
                    "kind": "depto",
                    "date": "2025-06-01",
                    "area": 60,
                    "year": year,
                    "uf": 3000 + i * 5,
                    "building": f"15105|{block}|PRUEBA|{number}",
                }
            )
    (tmp_path / "closings.json").write_text(json.dumps(closings), encoding="utf8")
    monkeypatch.setenv("SII_CLOSING_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flag,address",
    [
        ("false", "CALLE PRUEBA 100 DP 101"),
        ("false", {"invalid": 1}),
        ("false", 123),
        ("false", "x" * 1000),
        ("true", None),
        ("true", "__omit_address__"),
        ("true", ""),
        ("true", "  "),
    ],
)
async def test_release_response_identical_bytes(release_router, monkeypatch, flag, address):
    monkeypatch.setenv("sii_closing_layer", flag)

    def forbidden(**kwargs):
        pytest.fail("Inactive SII layer performed work")

    monkeypatch.setattr("services.sii.closing_opinion.build_opinion", forbidden)
    payload = {"comuna": "nunoa", "property_type": "apartment", "m2": 75, "address": address}
    if address == "__omit_address__":
        payload.pop("address")
    async with client(release_router) as old, client(valuations.router) as new:
        before = await old.post("/api/v1/valuations", json=payload)
        after = await new.post("/api/v1/valuations", json=payload)
    assert before.status_code == after.status_code == 200
    assert before.content == after.content
    assert "sii_closing_opinion" not in after.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "number,status,label",
    [
        (100, "available", "Confianza alta"),
        (200, "available", "Referencial"),
        (300, "unavailable", None),
        (400, "ambiguous", None),
    ],
)
async def test_enabled_branches_preserve_canonical_and_privacy(
    data, monkeypatch, release_router, number, status, label
):
    monkeypatch.setenv("sii_closing_layer", "true")
    payload = {
        "comuna": "nunoa",
        "property_type": "apartment",
        "m2": 75,
        "address": f"CALLE PRUEBA {number} DP 101",
    }
    async with client(release_router) as old, client(valuations.router) as new:
        before = await old.post("/api/v1/valuations", json=payload)
        after = await new.post("/api/v1/valuations", json=payload)
    assert before.status_code == after.status_code == 200
    body = after.json()
    opinion = body.pop("sii_closing_opinion")
    assert body == before.json()
    assert opinion["status"] == status
    assert opinion["confidence_label"] == label
    wire = json.dumps(opinion)
    for private in ("subject-", "synthetic-comp", "PRUEBA", "900001", "raw_id", "uf_m2", "rol"):
        assert private not in wire
    if status == "available":
        assert opinion["comparable_count"] == len(opinion["closing_dates"]) == 10
        assert opinion["p25_uf"] <= opinion["value_uf"] <= opinion["p75_uf"]
        assert opinion["area_m2"] == 60
    else:
        assert opinion["value_uf"] is None
        assert opinion["message"]
    if status == "ambiguous":
        assert opinion["candidate_count"] == 2
        assert len(opinion["candidates"]) == 2


def test_missing_config_is_safe(monkeypatch):
    monkeypatch.delenv("SII_CLOSING_DATA_DIR", raising=False)
    assert (
        build_opinion(
            address="CALLE PRUEBA 100", comuna="santiago", property_type="apartment", area=60
        )["reason_code"]
        == "data_unavailable"
    )


def test_too_few_closings_abstains_without_writing_index(data):
    path = data / "closings.json"
    path.write_text(json.dumps(json.loads(path.read_text())[:9]), encoding="utf8")
    index_before = (data / "address-index.sqlite").read_bytes()
    opinion = build_opinion(
        address="CALLE PRUEBA 100 DP 101",
        comuna="nunoa",
        property_type="apartment",
        area=60,
        data_dir=str(data),
    )
    assert opinion["reason_code"] == "insufficient_closings"
    assert "value_uf" not in opinion
    assert (data / "address-index.sqlite").read_bytes() == index_before


@pytest.mark.asyncio
async def test_sii_failure_preserves_current_result(monkeypatch, release_router):
    monkeypatch.setenv("sii_closing_layer", "true")

    def broken(**kwargs):
        raise RuntimeError("private-role-and-address-must-not-leak")

    monkeypatch.setattr("services.sii.closing_opinion.build_opinion", broken)
    payload = {
        "comuna": "nunoa",
        "property_type": "apartment",
        "m2": 75,
        "address": "CALLE PRUEBA 100",
    }
    async with client(release_router) as old, client(valuations.router) as new:
        before = await old.post("/api/v1/valuations", json=payload)
        after = await new.post("/api/v1/valuations", json=payload)
    body = after.json()
    opinion = body.pop("sii_closing_opinion")
    assert body == before.json()
    assert opinion["status"] == "unavailable"
    assert "private-role" not in after.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flag,enabled", [(None, False), ("true", True), ("false", False), ("TRUE", True)]
)
async def test_runtime_capability_default_off(monkeypatch, flag, enabled):
    if flag is None:
        monkeypatch.delenv("sii_closing_layer", raising=False)
    else:
        monkeypatch.setenv("sii_closing_layer", flag)
    async with client(valuations.router) as api:
        response = await api.get("/api/v1/tasar/capabilities")
    assert response.json() == {"sii_closing_layer": enabled}
