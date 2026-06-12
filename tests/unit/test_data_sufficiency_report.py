from __future__ import annotations

from decimal import Decimal

from core.value_objects.price import Price
from scripts.data_sufficiency_report import build_report
from tests.unit.factories import make_listing


def _listing(index: int, **kwargs):
    fingerprint = kwargs.pop("fingerprint", f"fp-{index}")
    listing = make_listing(fingerprint=fingerprint, **kwargs)
    listing.id = index
    return listing


def test_report_counts_active_useful_and_property_types() -> None:
    listings = [
        _listing(1, comuna="nunoa", property_type="apartment"),
        _listing(2, comuna="nunoa", property_type="house", built_area_m2=120, land_area_m2=300),
        _listing(3, comuna="macul", property_type="unknown"),
        _listing(4, comuna="macul", status="removed"),
    ]

    report = build_report(listings)

    assert report["summary"]["active_total"] == 3
    assert report["summary"]["avm_useful_total"] == 2
    assert report["by_property_type"] == {"apartment": 1, "house": 1, "unknown": 1}
    by_comuna = {row["comuna"]: row for row in report["by_comuna"]}
    assert by_comuna["nunoa"]["active_listings"] == 2
    assert by_comuna["nunoa"]["avm_useful_listings"] == 2
    assert by_comuna["macul"]["avm_useful_listings"] == 0


def test_report_counts_valid_m2_and_price() -> None:
    invalid_m2 = _listing(1, m2=0, built_area_m2=0, usable_area_m2=None)
    invalid_m2.built_area_m2 = None
    invalid_m2.usable_area_m2 = None
    invalid_price = _listing(2)
    invalid_price.price = Price(clp=Decimal("0"))
    valid = _listing(3)

    report = build_report([invalid_m2, invalid_price, valid])

    assert report["summary"]["valid_m2_total"] == 2
    assert report["summary"]["valid_price_total"] == 2
    assert report["summary"]["avm_useful_total"] == 1


def test_report_groups_geocode_precision() -> None:
    report = build_report(
        [
            _listing(1, geocode_precision="street_address"),
            _listing(2, geocode_precision="street_name"),
            _listing(3, geocode_precision="comuna_centroid"),
            _listing(4, geocode_precision="exact"),
            _listing(5, geocode_precision="address"),
            _listing(6, geocode_precision="comuna"),
            _listing(7, geocode_precision=None),
        ]
    )

    assert report["geocode_precision"] == {
        "address": 3,
        "street": 1,
        "comuna_centroid": 2,
        "unknown": 1,
    }


def test_report_marks_low_data_and_sufficient_comunas() -> None:
    nunoa = [_listing(i, comuna="nunoa") for i in range(1, 9)]
    macul = [_listing(i, comuna="macul") for i in range(20, 25)]
    vitacura = [_listing(i, comuna="vitacura") for i in range(30, 34)]

    report = build_report([*nunoa, *macul, *vitacura])
    by_comuna = {row["comuna"]: row for row in report["by_comuna"]}

    assert by_comuna["nunoa"]["low_data_mode"] is False
    assert by_comuna["nunoa"]["data_sufficient"] is True
    assert by_comuna["macul"]["low_data_mode"] is True
    assert by_comuna["macul"]["data_sufficient"] is True
    assert by_comuna["vitacura"]["low_data_mode"] is True
    assert by_comuna["vitacura"]["data_sufficient"] is False


def test_report_marks_low_data_by_comuna_and_property_type() -> None:
    apartments = [
        _listing(index, comuna="nunoa", property_type="apartment", fingerprint=f"apt-{index}")
        for index in range(1, 11)
    ]
    houses = [
        _listing(
            index,
            comuna="nunoa",
            property_type="house",
            built_area_m2=140,
            land_area_m2=400,
            fingerprint=f"house-{index}",
        )
        for index in range(20, 24)
    ]

    report = build_report([*apartments, *houses])
    by_comuna = {row["comuna"]: row for row in report["by_comuna"]}
    by_segment = {
        (row["comuna"], row["property_type"]): row
        for row in report["by_comuna_property_type"]
    }

    assert by_comuna["nunoa"]["low_data_mode"] is False
    assert by_segment[("nunoa", "apartment")]["low_data_mode"] is False
    assert by_segment[("nunoa", "apartment")]["data_sufficient"] is True
    assert by_segment[("nunoa", "house")]["low_data_mode"] is True
    assert by_segment[("nunoa", "house")]["data_sufficient"] is False
    assert report["summary"]["low_data_property_type_segments"] == 1


def test_report_includes_top_discard_reasons() -> None:
    listings = [
        _listing(1, comuna="nunoa", property_type="apartment", m2=75),
        _listing(2, comuna="nunoa", property_type="house", m2=75, built_area_m2=75, land_area_m2=200),
        _listing(3, comuna="macul", property_type="apartment", m2=75),
        _listing(4, comuna="nunoa", property_type="apartment", m2=200),
        _listing(5, comuna="nunoa", property_type="apartment", m2=75),
    ]

    report = build_report(listings)

    assert report["top_discard_reasons"]["property_type_mismatch"] >= 1
    assert report["top_discard_reasons"]["comuna_mismatch"] >= 1
    assert report["top_discard_reasons"]["area_out_of_range"] >= 1
