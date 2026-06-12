from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.value_objects.location import Coordinates
from infrastructure.external.nominatim_client import GeocodingResult
from scripts.geocode_listings import (
    BackfillStats,
    _process_listing,
    build_geocoding_query,
    build_geocoding_query_plan,
    classify_query_strength,
    clean_legacy_geo_hint,
    geocoding_rejection_reason,
    is_weak_geocoding_query,
    load_candidates,
    parse_args,
    validate_geocoding_result,
    write_post_run_report,
)


def test_comuna_centroid_query_is_treated_as_weak() -> None:
    listing = SimpleNamespace(title="Departamento en venta", comuna="santiago", raw_metadata={})

    query, precision = build_geocoding_query(listing)

    assert query == "Santiago, Santiago, Chile"
    assert precision == "comuna_centroid"
    assert is_weak_geocoding_query(query=query, precision=precision)


def test_street_address_query_is_not_weak() -> None:
    listing = SimpleNamespace(title="AV. PORTUGAL 451, Santiago", comuna="santiago", raw_metadata={})

    query, precision = build_geocoding_query(listing)

    assert query == "AV. PORTUGAL 451, Santiago, Chile"
    assert precision == "street_address"
    assert not is_weak_geocoding_query(query=query, precision=precision)


def test_no_query_is_weak() -> None:
    assert is_weak_geocoding_query(query=None, precision="unknown")


def test_query_with_only_comuna_and_country_is_weak_even_if_tagged_street() -> None:
    assert is_weak_geocoding_query(
        query="Las Condes, Chile",
        precision="street_name",
        comuna="las_condes",
    )


def test_marketing_slash_title_does_not_become_intersection() -> None:
    listing = SimpleNamespace(
        title="Para vivir/invertir presidente - riesco - el golf",
        comuna="las_condes",
        raw_metadata={},
    )

    query, precision = build_geocoding_query(listing)

    assert precision == "comuna_centroid"
    assert is_weak_geocoding_query(query=query, precision=precision, comuna="las_condes")


def test_street_without_number_stays_street_name() -> None:
    listing = SimpleNamespace(title="Departamento en Avenida Luis Thayer Ojeda", comuna="providencia", raw_metadata={})

    query, precision = build_geocoding_query(listing)

    assert query == "Avenida Luis Thayer Ojeda, Providencia, Chile"
    assert precision == "street_name"
    assert classify_query_strength(query=query, precision=precision, comuna="providencia") == "street_name"


def test_street_with_number_is_street_address() -> None:
    listing = SimpleNamespace(title="Departamento Avenida Portugal 451", comuna="santiago", raw_metadata={})

    query, precision = build_geocoding_query(listing)

    assert query == "Avenida Portugal 451, Santiago, Chile"
    assert precision == "street_address"


def test_metro_hint_is_not_address_strength() -> None:
    listing = SimpleNamespace(title="A pasos de Metro Irarrazaval", comuna="nunoa", raw_metadata={})

    query, precision = build_geocoding_query(listing)

    assert query == "Metro Irarrazaval, Nunoa, Chile"
    assert precision == "landmark_or_sector"
    assert is_weak_geocoding_query(query=query, precision=precision, comuna="nunoa")


def test_marketing_copy_after_street_is_removed_from_query() -> None:
    listing = SimpleNamespace(
        title="Departamento Av. Los Leones te ofrece una experiencia única UF 8000",
        comuna="providencia",
        raw_metadata={},
    )

    query, precision = build_geocoding_query(listing)

    assert query == "Av. Los Leones, Providencia, Chile"
    assert precision == "street_name"


def test_terrace_number_does_not_become_address() -> None:
    listing = SimpleNamespace(title="Departamento mas Terraza 145", comuna="nunoa", raw_metadata={})

    query, precision = build_geocoding_query(listing)

    assert query == "Nunoa, Santiago, Chile"
    assert precision == "comuna_centroid"
    assert is_weak_geocoding_query(query=query, precision=precision, comuna="nunoa")


def test_title_department_in_street_is_marked_as_low_confidence_title_inferred() -> None:
    listing = SimpleNamespace(title="Departamento en Emilio Vaisse", comuna="nunoa", raw_metadata={})

    plan = build_geocoding_query_plan(listing)

    assert plan.query == "Emilio Vaisse, Nunoa, Chile"
    assert plan.query_source == "title_inferred_street"
    assert plan.query_confidence == "low"
    assert plan.query_rule == "title_description.department_in_street"


def test_address_label_is_marked_as_metadata_address() -> None:
    listing = SimpleNamespace(
        title="Departamento en Providencia",
        comuna="providencia",
        raw_metadata={"address_label": "av. Antonio Varas comuna Providencia"},
    )

    plan = build_geocoding_query_plan(listing)

    assert plan.query == "Avenida Antonio Varas, Providencia, Chile"
    assert plan.query_source == "metadata_address"
    assert plan.query_confidence == "medium"
    assert plan.query_rule == "raw_metadata.address_label"
    assert plan.geocode_signal_type == "avenue"


def test_house_marketing_text_is_rejected_as_location_hint() -> None:
    listing = SimpleNamespace(
        title="CASA EN VENTA PEÑALOLEN CON PISCINA",
        comuna="penalolen",
        raw_metadata={"address_label": "CASA y PISCINA"},
    )

    query, precision = build_geocoding_query(listing)

    assert precision == "comuna_centroid"
    assert is_weak_geocoding_query(query=query, precision=precision, comuna="penalolen")


def test_real_street_hint_is_accepted_for_house() -> None:
    listing = SimpleNamespace(
        title="Casa en Avenida Buzeta",
        comuna="estacion_central",
        raw_metadata={"address_label": "Avenida Buzeta"},
    )

    assert build_geocoding_query(listing) == ("Avenida Buzeta, Estacion Central, Chile", "street_name")


def test_legacy_metro_caracteristicas_is_landmark_not_street() -> None:
    listing = SimpleNamespace(
        title="Departamento en venta",
        comuna="nunoa",
        raw_metadata={"address_label": "Metro Principe de GalesCARACTERÍSTICAS"},
    )

    plan = build_geocoding_query_plan(listing)

    assert plan.query == "Metro Principe de Gales, Nunoa, Chile"
    assert plan.precision == "landmark_or_sector"
    assert plan.query_source == "metadata_address"
    assert plan.geocode_signal_type == "metro"
    assert is_weak_geocoding_query(query=plan.query, precision=plan.precision, comuna="nunoa")


def test_legacy_metro_villa_frei_is_cleaned() -> None:
    cleaned = clean_legacy_geo_hint("Metro Villa FreiCARACTERÍSTICAS", comuna="nunoa")

    assert cleaned.cleaned_value == "Metro Villa Frei"
    assert cleaned.detected_signal_type == "metro"
    assert "suffix_removed" in cleaned.warnings


def test_legacy_marketing_hint_is_rejected() -> None:
    cleaned = clean_legacy_geo_hint("Lindo Penthouse y gran espacio", comuna="providencia")

    assert not cleaned.is_usable
    assert cleaned.reason == "marketing_text"


def test_legacy_street_with_commercial_suffix_is_trimmed() -> None:
    cleaned = clean_legacy_geo_hint("Av. Los Leones te ofrece una experiencia única ... UF", comuna="providencia")

    assert cleaned.is_usable
    assert cleaned.cleaned_value == "Avenida Los Leones"
    assert cleaned.detected_signal_type == "avenue"


def test_legacy_roberto_del_rio_fragment_is_rejected() -> None:
    cleaned = clean_legacy_geo_hint("calle Roberto del Río. La", comuna="providencia")

    assert not cleaned.is_usable
    assert cleaned.reason in {"too_many_tokens", "no_place_like_signal", "weak_trailing_fragment"}


def test_legacy_calle_interior_barrio_is_not_exact_street() -> None:
    cleaned = clean_legacy_geo_hint("calle interior de Barrio El Golf", comuna="las_condes")

    assert not cleaned.is_usable
    assert cleaned.reason == "weak_street_context"


def test_legacy_vicuna_mackenna_remains_usable_street() -> None:
    listing = SimpleNamespace(
        title="Departamento en Nunoa",
        comuna="nunoa",
        raw_metadata={"address_label": "Vicuña Mackenna"},
    )

    plan = build_geocoding_query_plan(listing)

    assert plan.query == "Vicuna Mackenna, Nunoa, Chile"
    assert plan.precision == "street_name"
    assert plan.query_source == "metadata_address"


def test_legacy_avenida_las_condes_keeps_warning() -> None:
    cleaned = clean_legacy_geo_hint("Avenida las Condes", comuna="las_condes")

    assert cleaned.is_usable
    assert cleaned.cleaned_value == "Avenida las Condes, Las Condes"
    assert "ambiguous_comuna_named_avenue" in cleaned.warnings


def test_geo_signal_candidate_street_generates_usable_query() -> None:
    listing = SimpleNamespace(
        title="Departamento en venta en Nunoa",
        comuna="nunoa",
        raw_metadata={
            "geo_signal_candidates": [
                {
                    "value": "Calle Portugal",
                    "normalized_value": "calle_portugal",
                    "signal_type": "street",
                    "source": "existing_microzone_metadata",
                    "confidence": "medium",
                    "rule": "street_pattern",
                }
            ]
        },
    )

    plan = build_geocoding_query_plan(listing)

    assert plan.query == "Calle Portugal, Nunoa, Chile"
    assert plan.precision == "street_name"
    assert plan.query_source == "geo_signal_candidate"
    assert plan.query_confidence == "medium"
    assert plan.geocode_signal_type == "street"
    assert plan.geocode_signal_source == "existing_microzone_metadata"
    assert not is_weak_geocoding_query(query=plan.query, precision=plan.precision, comuna="nunoa")


def test_geo_signal_candidate_avenue_generates_usable_query() -> None:
    listing = SimpleNamespace(
        title="Departamento en venta",
        comuna="providencia",
        raw_metadata={
            "geo_signal_candidates": [
                {
                    "value": "Avenida Pedro de Valdivia",
                    "normalized_value": "avenida_pedro_de_valdivia",
                    "signal_type": "avenue",
                    "source": "existing_microzone_metadata",
                    "confidence": "medium",
                    "rule": "avenue_pattern",
                }
            ]
        },
    )

    plan = build_geocoding_query_plan(listing)

    assert plan.query == "Avenida Pedro de Valdivia, Providencia, Chile"
    assert plan.precision == "street_name"
    assert plan.query_source == "geo_signal_candidate"
    assert plan.geocode_signal_type == "avenue"


def test_geo_signal_candidate_intersection_generates_usable_query() -> None:
    listing = SimpleNamespace(
        title="Departamento en venta",
        comuna="nunoa",
        raw_metadata={
            "geo_signal_candidates": [
                {
                    "value": "Manuel Montt y Valenzuela Castillo",
                    "normalized_value": "manuel_montt_y_valenzuela_castillo",
                    "signal_type": "intersection",
                    "source": "detail_text",
                    "confidence": "medium",
                    "rule": "intersection_pattern",
                }
            ]
        },
    )

    plan = build_geocoding_query_plan(listing)

    assert plan.query == "Manuel Montt y Valenzuela Castillo, Nunoa, Chile"
    assert plan.precision == "street_name"
    assert plan.query_source == "geo_signal_candidate"
    assert plan.geocode_signal_type == "intersection"


def test_geo_signal_candidate_metro_generates_weak_landmark_query() -> None:
    listing = SimpleNamespace(
        title="Departamento en venta",
        comuna="nunoa",
        raw_metadata={
            "geo_signal_candidates": [
                {
                    "value": "Metro Irarrazaval",
                    "normalized_value": "metro_irarrazaval",
                    "signal_type": "metro",
                    "source": "metadata_address",
                    "confidence": "medium",
                    "rule": "metro_pattern",
                }
            ]
        },
    )

    plan = build_geocoding_query_plan(listing)

    assert plan.query == "Metro Irarrazaval, Nunoa, Chile"
    assert plan.precision == "landmark_or_sector"
    assert plan.query_source == "geo_signal_candidate"
    assert plan.geocode_signal_type == "metro"
    assert is_weak_geocoding_query(query=plan.query, precision=plan.precision, comuna="nunoa")


def test_low_confidence_geo_signal_candidate_is_not_used() -> None:
    listing = SimpleNamespace(
        title="Departamento en venta",
        comuna="nunoa",
        raw_metadata={
            "geo_signal_candidates": [
                {
                    "value": "Calle Portugal",
                    "normalized_value": "calle_portugal",
                    "signal_type": "street",
                    "source": "title",
                    "confidence": "low",
                    "rule": "street_pattern",
                }
            ]
        },
    )

    plan = build_geocoding_query_plan(listing)

    assert plan.query_source == "comuna_fallback"
    assert plan.precision == "comuna_centroid"


def test_geo_signal_candidate_does_not_make_comuna_fallback_applicable() -> None:
    listing = SimpleNamespace(title="Departamento en venta", comuna="nunoa", raw_metadata={})

    plan = build_geocoding_query_plan(listing)

    assert plan.query_source == "comuna_fallback"
    assert is_weak_geocoding_query(query=plan.query, precision=plan.precision, comuna="nunoa")


def test_metadata_address_keeps_priority_over_geo_signal_candidate() -> None:
    listing = SimpleNamespace(
        title="Departamento en Providencia",
        comuna="providencia",
        raw_metadata={
            "address_label": "Avenida Antonio Varas",
            "geo_signal_candidates": [
                {
                    "value": "Avenida Pedro de Valdivia",
                    "normalized_value": "avenida_pedro_de_valdivia",
                    "signal_type": "avenue",
                    "source": "existing_microzone_metadata",
                    "confidence": "medium",
                    "rule": "avenue_pattern",
                }
            ],
        },
    )

    plan = build_geocoding_query_plan(listing)

    assert plan.query == "Avenida Antonio Varas, Providencia, Chile"
    assert plan.query_source == "metadata_address"
    assert plan.geocode_signal_type == "avenue"
    assert plan.geocode_signal_source == "raw_metadata.address_label"


def test_validate_rejects_generic_comuna_result() -> None:
    result = GeocodingResult(
        coordinates=Coordinates(-33.4489, -70.6693),
        query="Santiago, Chile",
        provider="nominatim",
        raw_class="boundary",
        raw_type="administrative",
        raw_addresstype="municipality",
        address={"country_code": "cl"},
    )

    assert validate_geocoding_result(result, requested_precision="street_name", expected_comuna="santiago") is None


def test_validate_rejects_comuna_mismatch() -> None:
    result = GeocodingResult(
        coordinates=Coordinates(-33.42, -70.61),
        query="Avenida Providencia, Providencia, Chile",
        provider="nominatim",
        raw_class="highway",
        raw_type="residential",
        raw_addresstype="road",
        address={"country_code": "cl", "suburb": "Las Condes"},
    )

    assert validate_geocoding_result(result, requested_precision="street_name", expected_comuna="providencia") is None
    assert geocoding_rejection_reason(result, requested_precision="street_name", expected_comuna="providencia") == "conflicting_comuna"


def test_validate_classifies_street_address_with_house_number_as_address() -> None:
    result = GeocodingResult(
        coordinates=Coordinates(-33.442, -70.646),
        query="Lord Cochrane 635, Santiago, Chile",
        provider="nominatim",
        raw_class="place",
        raw_type="house",
        raw_addresstype="house",
        address={"country_code": "cl", "house_number": "635"},
    )

    validated = validate_geocoding_result(result, requested_precision="street_address", expected_comuna="santiago")

    assert validated is not None
    assert validated.precision == "address"


@pytest.mark.asyncio
async def test_load_candidates_includes_houses_when_property_type_is_not_set() -> None:
    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return []

    class FakeSession:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return FakeResult()

    session = FakeSession()
    await load_candidates(session, limit=None)

    assert "where listings.property_type" not in str(session.statement).lower()


@pytest.mark.asyncio
async def test_load_candidates_can_filter_house_property_type() -> None:
    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return []

    class FakeSession:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return FakeResult()

    session = FakeSession()
    await load_candidates(session, limit=None, property_type="house")

    assert "property_type" in str(session.statement).lower()


@pytest.mark.asyncio
async def test_existing_coordinates_are_not_overwritten() -> None:
    listing = SimpleNamespace(
        id=1,
        title="Avenida Portugal 451",
        comuna="santiago",
        raw_metadata={},
        lat=-33.4,
        lon=-70.6,
    )
    stats = BackfillStats()
    geocoder = SimpleNamespace(last_cache_hit=False)
    session = SimpleNamespace(add=lambda _: None)

    await _process_listing(
        session,
        geocoder,
        listing,
        stats,
        dry_run=True,
        apply=False,
        sleep_seconds=1.0,
        no_external=False,
        examples_limit=3,
    )

    assert stats.skipped_existing_coordinates == 1
    assert stats.examples[0].reason == "existing_coordinates_not_overwritten"
    assert listing.lat == -33.4
    assert listing.lon == -70.6


@pytest.mark.asyncio
async def test_dry_run_does_not_write_coordinates() -> None:
    class FakeGeocoder:
        last_cache_hit = False

        async def geocode(self, query: str, comuna: str) -> Coordinates:
            return Coordinates(lat=-33.45, lon=-70.66)

    added: list[object] = []
    listing = SimpleNamespace(
        id=2,
        title="Avenida Portugal 451",
        comuna="santiago",
        raw_metadata={},
        lat=None,
        lon=None,
    )
    stats = BackfillStats()
    session = SimpleNamespace(add=added.append)

    await _process_listing(
        session,
        FakeGeocoder(),
        listing,
        stats,
        dry_run=True,
        apply=False,
        sleep_seconds=0.0,
        no_external=False,
        examples_limit=3,
    )

    assert stats.would_geocode == 1
    assert added == []
    assert listing.lat is None
    assert listing.lon is None


@pytest.mark.asyncio
async def test_apply_writes_geocode_source_and_confidence_metadata() -> None:
    class FakeGeocoder:
        last_cache_hit = False

        async def geocode_with_metadata(self, query: str, comuna: str) -> GeocodingResult:
            return GeocodingResult(
                coordinates=Coordinates(lat=-33.442, lon=-70.646),
                query=query,
                provider="nominatim",
                raw_class="place",
                raw_type="house",
                raw_addresstype="house",
                address={"country_code": "cl", "house_number": "451"},
                display_name="Avenida Portugal 451, Santiago",
            )

    added: list[object] = []
    listing = SimpleNamespace(
        id=3,
        title="Avenida Portugal 451",
        comuna="santiago",
        raw_metadata={"existing_key": "keep", "address_label": "Avenida Portugal 451"},
        lat=None,
        lon=None,
        geocode_precision=None,
    )
    stats = BackfillStats(dry_run=False)
    session = SimpleNamespace(add=added.append)

    await _process_listing(
        session,
        FakeGeocoder(),
        listing,
        stats,
        dry_run=False,
        apply=True,
        sleep_seconds=0.0,
        no_external=False,
        examples_limit=3,
    )

    assert stats.geocoded == 1
    assert listing.geocode_precision == "address"
    assert listing.raw_metadata["existing_key"] == "keep"
    assert listing.raw_metadata["geocode_source"] == "nominatim"
    assert listing.raw_metadata["geocode_confidence"] > 0
    assert listing.raw_metadata["geocode_provider"] == "nominatim"
    assert listing.raw_metadata["geocode_query"] == "Avenida Portugal 451, Santiago, Chile"
    assert listing.raw_metadata["geocode_query_source"] == "metadata_address"
    assert listing.raw_metadata["geocode_query_confidence"] == "medium"
    assert listing.raw_metadata["geocode_query_rule"] == "raw_metadata.address_label"
    assert listing.raw_metadata["geocode_precision"] == "address"
    assert listing.raw_metadata["geocode_applied_at"]
    assert listing.raw_metadata["geocode_version"] == "geocode_backfill_v1"
    assert listing.raw_metadata["geocode_score"] == listing.raw_metadata["geocode_confidence"]
    assert added == [listing]


@pytest.mark.asyncio
async def test_title_inferred_street_is_not_applied_by_default() -> None:
    class FakeGeocoder:
        last_cache_hit = False

        async def geocode_with_metadata(self, query: str, comuna: str) -> GeocodingResult:
            raise AssertionError("title inferred apply should be blocked before geocoding")

    added: list[object] = []
    listing = SimpleNamespace(
        id=30,
        title="Departamento en Emilio Vaisse",
        comuna="nunoa",
        raw_metadata={},
        lat=None,
        lon=None,
        geocode_precision=None,
    )
    stats = BackfillStats(dry_run=False)
    session = SimpleNamespace(add=added.append)

    await _process_listing(
        session,
        FakeGeocoder(),
        listing,
        stats,
        dry_run=False,
        apply=True,
        sleep_seconds=0.0,
        no_external=False,
        examples_limit=3,
    )

    assert stats.title_inferred_blocked == 1
    assert stats.rejection_reasons["title_inferred_requires_explicit_flag"] == 1
    assert stats.examples[0].query_source == "title_inferred_street"
    assert stats.examples[0].query_confidence == "low"
    assert added == []
    assert listing.lat is None


@pytest.mark.asyncio
async def test_title_inferred_street_is_applied_with_explicit_flag() -> None:
    class FakeGeocoder:
        last_cache_hit = False

        async def geocode_with_metadata(self, query: str, comuna: str) -> GeocodingResult:
            return GeocodingResult(
                coordinates=Coordinates(lat=-33.455, lon=-70.61),
                query=query,
                provider="nominatim",
                raw_class="highway",
                raw_type="residential",
                raw_addresstype="road",
                address={"country_code": "cl"},
            )

    added: list[object] = []
    listing = SimpleNamespace(
        id=31,
        title="Departamento en Emilio Vaisse",
        comuna="nunoa",
        raw_metadata={"existing_key": "keep"},
        lat=None,
        lon=None,
        geocode_precision=None,
    )
    stats = BackfillStats(dry_run=False)
    session = SimpleNamespace(add=added.append)

    await _process_listing(
        session,
        FakeGeocoder(),
        listing,
        stats,
        dry_run=False,
        apply=True,
        sleep_seconds=0.0,
        no_external=False,
        allow_title_inferred=True,
        examples_limit=3,
    )

    assert stats.geocoded == 1
    assert listing.raw_metadata["existing_key"] == "keep"
    assert listing.raw_metadata["geocode_query_source"] == "title_inferred_street"
    assert listing.raw_metadata["geocode_query_confidence"] == "low"
    assert listing.raw_metadata["geocode_query_rule"] == "title_description.department_in_street"
    assert added == [listing]


@pytest.mark.asyncio
async def test_street_hint_remains_applicable_as_street_precision() -> None:
    class FakeGeocoder:
        last_cache_hit = False

        async def geocode_with_metadata(self, query: str, comuna: str) -> GeocodingResult:
            return GeocodingResult(
                coordinates=Coordinates(lat=-33.435, lon=-70.617),
                query=query,
                provider="nominatim",
                raw_class="highway",
                raw_type="primary",
                raw_addresstype="road",
                address={"country_code": "cl"},
            )

    added: list[object] = []
    listing = SimpleNamespace(
        id=33,
        title="Departamento en Providencia",
        comuna="providencia",
        raw_metadata={"street_hint": "Avenida Providencia"},
        lat=None,
        lon=None,
        geocode_precision=None,
    )
    stats = BackfillStats(dry_run=False)
    session = SimpleNamespace(add=added.append)

    await _process_listing(
        session,
        FakeGeocoder(),
        listing,
        stats,
        dry_run=False,
        apply=True,
        sleep_seconds=0.0,
        no_external=False,
        examples_limit=3,
    )

    assert stats.geocoded == 1
    assert listing.geocode_precision == "street"
    assert listing.raw_metadata["geocode_query_source"] == "metadata_street_hint"
    assert listing.raw_metadata["geocode_query_confidence"] == "medium"
    assert listing.raw_metadata["geocode_query_rule"] == "raw_metadata.street_hint"
    assert added == [listing]


@pytest.mark.asyncio
@pytest.mark.parametrize("raw_type", ["railway", "park"])
async def test_apply_rejects_unsupported_street_raw_type(raw_type: str) -> None:
    class FakeGeocoder:
        last_cache_hit = False

        async def geocode_with_metadata(self, query: str, comuna: str) -> GeocodingResult:
            return GeocodingResult(
                coordinates=Coordinates(lat=-33.455, lon=-70.61),
                query=query,
                provider="nominatim",
                raw_class="railway" if raw_type == "railway" else "leisure",
                raw_type=raw_type,
                raw_addresstype=raw_type,
                address={"country_code": "cl"},
            )

    added: list[object] = []
    listing = SimpleNamespace(
        id=32,
        title="Departamento en Providencia",
        comuna="providencia",
        raw_metadata={"street_hint": "Avenida Providencia"},
        lat=None,
        lon=None,
        geocode_precision=None,
    )
    stats = BackfillStats(dry_run=False)
    session = SimpleNamespace(add=added.append)

    await _process_listing(
        session,
        FakeGeocoder(),
        listing,
        stats,
        dry_run=False,
        apply=True,
        sleep_seconds=0.0,
        no_external=False,
        examples_limit=3,
    )

    assert stats.rejected_by_guardrails == 1
    assert stats.rejection_reasons["unsupported_street_raw_type"] == 1
    assert added == []
    assert listing.lat is None


@pytest.mark.asyncio
async def test_apply_rejects_wrong_comuna_and_does_not_write() -> None:
    class FakeGeocoder:
        last_cache_hit = False

        async def geocode_with_metadata(self, query: str, comuna: str) -> GeocodingResult:
            return GeocodingResult(
                coordinates=Coordinates(lat=-33.42, lon=-70.61),
                query=query,
                provider="nominatim",
                raw_class="highway",
                raw_type="residential",
                raw_addresstype="road",
                address={"country_code": "cl", "suburb": "Las Condes"},
            )

    added: list[object] = []
    listing = SimpleNamespace(
        id=4,
        title="Avenida Providencia 1200",
        comuna="providencia",
        raw_metadata={"street_hint": "Avenida Providencia 1200"},
        lat=None,
        lon=None,
        geocode_precision=None,
    )
    stats = BackfillStats(dry_run=False)
    session = SimpleNamespace(add=added.append)

    await _process_listing(
        session,
        FakeGeocoder(),
        listing,
        stats,
        dry_run=False,
        apply=True,
        sleep_seconds=0.0,
        no_external=False,
        examples_limit=3,
    )

    assert stats.rejected_by_guardrails == 1
    assert stats.rejection_reasons["conflicting_comuna"] == 1
    assert added == []
    assert listing.lat is None
    assert listing.lon is None


@pytest.mark.asyncio
async def test_apply_rejects_suspicious_repeated_coordinates() -> None:
    class FakeGeocoder:
        last_cache_hit = False

        async def geocode_with_metadata(self, query: str, comuna: str) -> GeocodingResult:
            return GeocodingResult(
                coordinates=Coordinates(lat=-33.442, lon=-70.646),
                query=query,
                provider="nominatim",
                raw_class="place",
                raw_type="house",
                raw_addresstype="house",
                address={"country_code": "cl", "house_number": "451"},
            )

    class FakeResult:
        def scalar_one(self) -> int:
            return 8

    class FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []

        async def execute(self, statement):
            return FakeResult()

        def add(self, listing):
            self.added.append(listing)

    listing = SimpleNamespace(
        id=5,
        title="Avenida Portugal 451",
        comuna="santiago",
        raw_metadata={"address_label": "Avenida Portugal 451"},
        lat=None,
        lon=None,
        geocode_precision=None,
    )
    stats = BackfillStats(dry_run=False)
    session = FakeSession()

    await _process_listing(
        session,
        FakeGeocoder(),
        listing,
        stats,
        dry_run=False,
        apply=True,
        sleep_seconds=0.0,
        no_external=False,
        examples_limit=3,
    )

    assert stats.repeated_coordinates == 1
    assert stats.rejected_by_guardrails == 1
    assert stats.rejection_reasons["repeated_coordinates"] == 1
    assert session.added == []
    assert listing.lat is None


def test_parse_args_supports_commune_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["geocode_listings.py", "--commune", "providencia", "--limit", "10"])

    args = parse_args()

    assert args.comuna == "providencia"
    assert args.limit == 10


def test_write_post_run_report_creates_latest_files() -> None:
    stats = BackfillStats()
    stats.total_candidates = 2
    stats.would_geocode = 1
    stats.skipped = 1
    stats.precision_counts["street_name"] = 1
    stats.by_comuna["santiago"] = 2

    output_dir = Path("reports/test_geocode_backfill")
    md_path, json_path = write_post_run_report(stats, output_dir=output_dir)

    assert md_path.exists()
    assert json_path.exists()
    assert "AVM Geocode Backfill Report" in md_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["precision_counts"] == {"street": 1}
    assert "rejected_by_guardrails" in payload
    assert "rejection_reasons" in payload
