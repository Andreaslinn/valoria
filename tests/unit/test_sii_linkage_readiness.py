from copy import deepcopy

from scripts.audit_sii_linkage_readiness import analyze, exact_address, facts, main


def row(comuna="Santiago", identity="123"):
    return {
        "id": int(identity),
        "source": "portalinmobiliario",
        "external_id": "MLC-" + identity,
        "comuna": comuna,
        "url": "https://www.portalinmobiliario.com/MLC-" + identity,
        "lat": None,
        "lon": None,
        "published_fields": {
            "version": 1,
            "source": "portalinmobiliario",
            "external_id": identity,
            "stage": "detail",
            "street": "LOS LEONES",
            "address_number": "1500",
            "address_type": "exact",
            "address_raw": "Los Leones 1500 Depto 204",
            "apartment_number": "204",
            "latitude": -33.43,
            "longitude": -70.60,
            "coordinates_origin": "portal:location.map_info",
            "coordinates_precision": "unknown",
            "useful_area_m2": 70,
            "provenance": {
                "address": "portal:location.map_info.item_address",
                "useful_area_m2": "portal.technical_specifications.superficie_util",
            },
        },
    }


def test_disabled_before_database_environment_access(monkeypatch, capsys):
    monkeypatch.delenv("SII_LINKAGE_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    main()
    assert '"status": "disabled"' in capsys.readouterr().out


def test_published_fields_are_bound_to_identity_and_portal():
    r = row()
    assert facts(r)["los_tres_campos"]
    r["published_fields"]["external_id"] = "999"
    assert not facts(r)["direccion_o_coordenadas"]
    r["published_fields"]["external_id"] = "123"
    r["published_fields"]["source"] = "yapo"
    assert not facts(r)["snapshot_PR5"]


def test_apartment_number_never_becomes_street_number():
    f = row()["published_fields"]
    f.update(address_raw="Los Leones, Depto 204", address_number="204")
    assert exact_address(f) == (False, "numero_departamento_usado_como_calle")
    f.update(address_raw="Los Leones 204 Depto 204")
    assert exact_address(f) == (True, None)
    f.update(street="Depto", address_number="204")
    assert not exact_address(f)[0]


def test_coordinates_unknown_count_as_observed_but_centroids_do_not():
    r = row()
    assert facts(r)["coordenadas_publicadas"]
    assert facts(r)["coordenadas_precision_desconocida"]
    r["published_fields"]["coordinates_precision_raw"] = {"is_centroid": True}
    assert not facts(r)["coordenadas_publicadas"]
    r["lat"], r["lon"] = -33.43, -70.60
    assert facts(r)["coordenadas_canonicas"]
    assert not facts(r)["coordenadas_publicadas"]


def test_usable_area_requires_explicit_provenance_and_accepts_bound_detail():
    r = row()
    r["usable_area_m2"] = 70
    r["published_fields"]["provenance"]["useful_area_m2"] = "fallback.generic_m2"
    assert not facts(r)["m2_util_explicito"]
    r["published_detail_fields"] = deepcopy(row()["published_fields"])
    assert facts(r)["m2_util_explicito"]


def test_gate_uses_union_and_strict_majority_without_rounding():
    rows = []
    names = [
        "Vitacura",
        "Las Condes",
        "Ñuñoa",
        "Providencia",
        "La Florida",
        "Santiago",
        "San Miguel",
        "Estación Central",
    ]
    for i, name in enumerate(names):
        r = row(name, str(i + 1))
        if i < 4:
            r["published_fields"] = None
        rows.append(r)
    report = analyze(rows, "2026-10-19T00:00:00Z")
    assert len(report["gate"]["communes_below_40"]) == 4
    assert not report["gate"]["stop"]
    rows[4]["published_fields"] = None
    report = analyze(rows, "2026-10-19T00:00:00Z")
    assert report["gate"]["stop"]
    assert len(report["por_comuna_y_portal"]) == 16
    assert report["total"]["conteos"]["direccion_o_coordenadas"] == 3


def test_gate_passes_exactly_forty_percent():
    rows = [row(identity=str(i + 1)) for i in range(5)]
    for r in rows[2:]:
        r["published_fields"] = None
    report = analyze(rows, "now")
    s = next(r for r in report["por_comuna"] if r["comuna"] == "santiago")
    assert s["porcentajes"]["direccion_o_coordenadas"] == 40
    assert not s["bajo_40"]
