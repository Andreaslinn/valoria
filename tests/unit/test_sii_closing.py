from __future__ import annotations

import sqlite3

import pytest

from config.valuation_flags import sii_closing_layer_enabled
from services.sii.closing_address import SCHEMA, AddressIndex, parse_address
from services.sii.closing_knn import ClosingKNN, weighted_quantile


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Av. Irarrázaval 01001 dpto. 802", ("IRARRAZAVAL", "1001", "802", None, None)),
        (
            "avenida irarrazaval N° 1001 departamento 802",
            ("IRARRAZAVAL", "1001", "802", None, None),
        ),
        ("11 de Septiembre 1234 DP 101", ("11 DE SEPTIEMBRE", "1234", "101", None, None)),
        ("Dr. Sótero del Río 504, piso 3", ("DOCTOR SOTERO DEL RIO", "504", None, 3, None)),
        ("Pje. Sta. María 52 A depto 12 B", ("SANTA MARIA", "52A", "12B", None, None)),
        ("Micalvi 501 block 35 dpto 204", ("MICALVI", "501", "204", None, "35")),
        ("H TRUCCO 41 DPTO 32", ("H TRUCCO", "41", "32", None, None)),
        ("AVENIDA APOQUINDO", ("APOQUINDO", None, None, None, None)),
        ("AV DEPARTAMENTAL 960 DP 607", ("DEPARTAMENTAL", "960", "607", None, None)),
        ("SN J DE LA ESTRELLA 921 C DP 11", ("SAN J DE LA ESTRELLA", "921C", "11", None, None)),
    ],
)
def test_address(raw, expected):
    a = parse_address(raw)
    assert (a.street, a.number, a.unit, a.floor, a.tower) == expected


@pytest.fixture
def index(tmp_path):
    path = tmp_path / "address.sqlite"
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    c.executemany(
        "INSERT INTO role VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                "1-5-1",
                1,
                5,
                "SANTA MARIA",
                "100",
                "101",
                None,
                "STA MARIA 100 DP 101",
                "depto",
                2000,
                60,
                1,
            ),
            (
                "1-5-2",
                1,
                5,
                "SANTA MARIA",
                "100",
                "102",
                None,
                "STA MARIA 100 DP 102",
                "depto",
                2000,
                70,
                1,
            ),
            (
                "1-6-1",
                1,
                6,
                "COLISION",
                "200",
                "1",
                None,
                "COLISION 200 DP 1",
                "depto",
                2000,
                70,
                1,
            ),
            (
                "1-7-1",
                1,
                7,
                "COLISION",
                "200",
                "2",
                None,
                "COLISION 200 DP 2",
                "depto",
                2000,
                70,
                1,
            ),
        ],
    )
    c.commit()
    c.close()
    result = AddressIndex(path)
    yield result
    result.close()


def test_building_and_unit(index):
    assert index.resolve(1, "Santa María 100")["status"] == "building"
    result = index.resolve(1, "Sta. María 100 depto. 101")
    assert result["status"] == "unit"
    assert result["role"]["rol"] == "1-5-1"


def test_ambiguity_never_selects(index):
    for address, reason in [
        ("COLISION 200", "multiple_buildings"),
        ("SANTA MARIA 100 PISO 1", "floor_not_recorded_in_catastro"),
        ("SANTA MARIA 100 DP 999", "unit_not_found"),
    ]:
        result = index.resolve(1, address)
        assert result["status"] == "ambiguous"
        assert result["reason"] == reason
        assert "role" not in result
        assert result["candidates"]


def test_osm_only_after_text_miss_and_keeps_number_and_commune(index):
    calls = []

    def fallback(code, street, number):
        calls.append((code, street, number))
        return ["Santa Maria"]

    assert index.resolve(1, "Santa María 100", fallback)["method"] == "catastro_text"
    assert calls == []
    assert index.resolve(1, "Santa Mari 100", fallback)["method"] == "osm_text_fallback"
    assert index.resolve(1, "Santa Mari 101", fallback)["status"] == "unresolved"
    assert index.resolve(2, "Santa Mari 100", fallback)["status"] == "unresolved"


def row(i, **kw):
    return {
        "rol": f"1-5-{i}",
        "comuna": 1,
        "block": 5,
        "kind": "depto",
        "date": "2025-01-01",
        "area": 60.0,
        "year": 2000,
        "building": "1|5|STREET|100",
        "uf": 6000.0,
        "raw_id": i,
        **kw,
    }


def test_knn_closed_area_quantiles_and_role_time_leakage():
    pool = [row(i, uf=(i + 90) * 60.0) for i in range(1, 11)]
    pool += [row(11, date="2026-05-01", uf=1), row(12, uf=1), row(13, uf=1)]
    model = ClosingKNN(pool, excluded_roles={"1-5-13"})
    result = model.estimate(row(12, date="2026-01-01"))
    assert result["status"] == "ok"
    assert result["value_uf"] == 95 * 60
    assert result["p25_uf"] == 93 * 60
    assert result["p75_uf"] == 98 * 60
    assert len(result["comparables"]) == 10
    assert {r["rol"] for r in result["comparables"]} == {f"1-5-{i}" for i in range(1, 11)}


def test_same_building_outranks_same_block_then_commune():
    pool = [row(i, block=9, building="elsewhere") for i in range(1, 11)]
    pool += [row(11, building="other_block_building"), row(12)]
    result = ClosingKNN(pool).estimate(row(20, date="2026-01-01"))
    assert result["comparables"][0]["rol"] == "1-5-12"
    assert result["comparables"][1]["rol"] == "1-5-11"


def test_less_than_ten_and_unknown_age_abstain():
    model = ClosingKNN([row(i) for i in range(1, 10)])
    assert model.estimate(row(20, date="2026-01-01"))["reason"] == "fewer_than_10_comparables"
    assert model.estimate(row(20, year=None))["status"] == "unavailable"


def test_area_bounds_and_same_commune_type_only():
    pool = [row(i, area=1000) for i in range(1, 11)]
    pool += [row(i, comuna=2) for i in range(11, 21)]
    pool += [row(i, kind="casa") for i in range(21, 31)]
    assert ClosingKNN(pool).estimate(row(50, date="2026-01-01"))["status"] == "unavailable"


@pytest.mark.parametrize("area", [None, 0, float("nan")])
def test_missing_or_invalid_closed_surface_abstains(area):
    model = ClosingKNN([row(i) for i in range(1, 11)])
    assert model.estimate(row(50, date="2026-01-01", area=area))["status"] == "unavailable"
    assert not ClosingKNN([row(1, area=area)]).rows


@pytest.mark.parametrize(
    ("values", "weights"),
    [([], []), ([1, 2], [1, -0.1]), ([float("nan")], [1]), ([1], [float("inf")])],
)
def test_invalid_quantiles(values, weights):
    with pytest.raises(ValueError):
        weighted_quantile(values, weights, 0.5)


def test_flag_is_off_by_default(monkeypatch):
    monkeypatch.delenv("sii_closing_layer", raising=False)
    assert not sii_closing_layer_enabled()
    monkeypatch.setenv("sii_closing_layer", "true")
    assert sii_closing_layer_enabled()
