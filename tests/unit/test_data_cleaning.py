"""Tests unitarios de data_cleaning.clean_listing."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.exceptions import UnknownComunaError, ValidationError
from core.value_objects.location import Coordinates
from domain.ingestion.data_cleaning import (
    clean_listing,
    extract_area_fields,
    normalize_location_text,
)


def _valid_raw(**overrides) -> dict:
    base = {
        "source": "yapo",
        "external_id": "ext-123",
        "title": "Depto 3D/2B en Ñuñoa",
        "comuna": "Ñuñoa",
        "m2": 75,
        "bedrooms": 3,
        "bathrooms": 2,
        "parking": 1,
        "price_clp": 180_000_000,
        "url": "https://yapo.cl/abc",
        "lat": -33.4569,
        "lon": -70.5969,
        "scraped_at": datetime(2026, 4, 23, 10, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return base


class TestHappyPath:
    def test_clean_returns_expected_fields(self):
        result = clean_listing(_valid_raw())
        assert result.source == "yapo"
        assert result.comuna == "nunoa"  # normalizado
        assert result.property_type == "apartment"
        assert result.m2 == 75.0
        assert result.built_area_m2 == 75.0
        assert result.usable_area_m2 == 75.0
        assert result.land_area_m2 is None
        assert result.bedrooms == 3
        assert result.price.clp == Decimal("180000000")
        assert result.coordinates == Coordinates(-33.4569, -70.5969)
        assert result.geocode_precision == "address"

    def test_parking_default_zero(self):
        raw = _valid_raw()
        del raw["parking"]
        assert clean_listing(raw).parking == 0

    def test_raw_metadata_preserved(self):
        raw = _valid_raw(raw_metadata={"source_page": 3, "featured": True})
        result = clean_listing(raw)
        assert result.raw_metadata["source_page"] == 3
        assert result.raw_metadata["featured"] is True

    def test_address_hint_marks_address_precision(self):
        result = clean_listing(
            _valid_raw(
                lat=None,
                lon=None,
                raw_metadata={"address": "Lord Cochrane 635"},
            )
        )
        assert result.geocode_precision == "street"

    def test_known_comuna_without_address_marks_comuna_precision(self):
        result = clean_listing(_valid_raw(lat=None, lon=None))

        assert result.geocode_precision == "comuna"

    def test_scraped_at_defaults_to_now_when_missing(self):
        raw = _valid_raw()
        del raw["scraped_at"]
        result = clean_listing(raw)
        assert result.scraped_at is not None
        assert (datetime.now(UTC) - result.scraped_at).total_seconds() < 5


class TestComunaNormalization:
    def test_accents_stripped(self):
        assert clean_listing(_valid_raw(comuna="Ñuñoa")).comuna == "nunoa"
        assert clean_listing(_valid_raw(title="Departamento amplio", comuna="Peñalolén")).comuna == "penalolen"

    def test_uppercase_lowered(self):
        assert clean_listing(_valid_raw(title="Departamento amplio", comuna="LAS CONDES")).comuna == "las_condes"

    def test_unknown_comuna_raises(self):
        with pytest.raises(UnknownComunaError):
            clean_listing(_valid_raw(title="Departamento amplio", comuna="Marte"))

    @pytest.mark.parametrize(
        ("raw_value", "expected"),
        [
            ("stgo", "santiago"),
            ("Santiago Centro", "santiago"),
            ("nunoa", "nunoa"),
            ("las condes rm", "las_condes"),
            ("Est. Central", "estacion_central"),
            ("depto en Peñalolén!!!", "penalolen"),
            ("Venta departamento La Florida, RM", "la_florida"),
            ("Lo Barnechea", "lo_barnechea"),
            ("Huechuraba", "huechuraba"),
            ("Quilicura", "quilicura"),
            ("Cerrillos", "cerrillos"),
            ("Conchalí", "conchali"),
            ("Quinta Normal", "quinta_normal"),
            ("Lo Prado", "lo_prado"),
            ("Pedro Aguirre Cerda", "pedro_aguirre_cerda"),
            ("San Joaquín", "san_joaquin"),
            ("La Cisterna", "la_cisterna"),
            ("El Bosque", "el_bosque"),
            ("San Ramón", "san_ramon"),
            ("La Granja", "la_granja"),
        ],
    )
    def test_alias_and_fuzzy_normalization(self, raw_value, expected):
        assert clean_listing(_valid_raw(title="Departamento amplio", comuna=raw_value)).comuna == expected

    def test_normalize_location_text_removes_noise(self):
        assert (
            normalize_location_text("Las Condes RM, Región Metropolitana, Santiago Chile!!")
            == "las condes"
        )

    def test_extracts_comuna_from_title_before_location(self):
        result = clean_listing(
            _valid_raw(
                title="Departamento remodelado en Ñuñoa",
                comuna="Las Condes",
            )
        )
        assert result.comuna == "nunoa"
        assert result.raw_metadata["comuna_extraction_source"] == "title"
        assert result.raw_metadata["comuna_match_strategy"] == "partial_match"
        assert result.raw_metadata["comuna_match_value"] == "nunoa"

    def test_extracts_comuna_from_location_text(self):
        raw = _valid_raw(
            title="Departamento remodelado",
            comuna="Región Metropolitana",
            location="Avenida Apoquindo, Las Condes RM",
        )
        result = clean_listing(raw, allow_incomplete=True)
        assert result.comuna == "las_condes"
        assert result.raw_metadata["comuna_extraction_source"] == "location"
        assert result.raw_metadata["comuna_match_strategy"] == "partial_match"
        assert result.raw_metadata["comuna_match_value"] == "las condes"
        assert "unknown_comuna" not in result.quality_warnings

    def test_extracts_comuna_from_description_after_location(self):
        raw = _valid_raw(
            title="Departamento remodelado",
            comuna="Región Metropolitana",
            description="Cercano a metro en San Miguel.",
        )
        result = clean_listing(raw, allow_incomplete=True)
        assert result.comuna == "san_miguel"
        assert result.raw_metadata["comuna_extraction_source"] == "description"
        assert result.raw_metadata["comuna_match_strategy"] == "partial_match"
        assert result.raw_metadata["comuna_match_value"] == "san miguel"

    def test_alias_strategy_is_tracked(self):
        result = clean_listing(_valid_raw(title="Departamento amplio", comuna="stgo"))
        assert result.comuna == "santiago"
        assert result.raw_metadata["comuna_match_strategy"] == "alias"
        assert result.raw_metadata["comuna_match_value"] == "stgo"

    def test_unknown_comuna_in_incomplete_mode_is_not_rejected(self):
        result = clean_listing(_valid_raw(title="Departamento amplio", comuna="Valparaíso"), allow_incomplete=True)
        assert result.comuna == "valparaiso"
        assert result.raw_metadata["data_quality_warnings"] == ["unknown_comuna"]
        assert result.raw_metadata["outside_rm_candidate"] is True
        assert result.raw_metadata["comuna_extraction_attempts"]


class TestSourceValidation:
    def test_rejects_unknown_source(self):
        with pytest.raises(ValidationError):
            clean_listing(_valid_raw(source="craigslist"))

    def test_accepts_valid_sources(self):
        for src in ["yapo", "portalinmobiliario", "app", "geocoding"]:
            assert clean_listing(_valid_raw(source=src)).source == src


class TestPriceParsing:
    def test_integer(self):
        assert clean_listing(_valid_raw(price_clp=180_000_000)).price.clp == Decimal(180_000_000)

    def test_decimal(self):
        assert (
            clean_listing(_valid_raw(price_clp=Decimal("180000000.00"))).price.clp
            == Decimal(180_000_000)
        )

    def test_string_with_dots_as_thousands(self):
        assert clean_listing(_valid_raw(price_clp="180.000.000")).price.clp == Decimal(180_000_000)

    def test_string_with_dollar_sign(self):
        assert clean_listing(_valid_raw(price_clp="$180.000.000")).price.clp == Decimal(180_000_000)

    def test_string_with_clp_suffix(self):
        assert clean_listing(_valid_raw(price_clp="180,000,000 CLP")).price.clp == Decimal(180_000_000)

    def test_below_minimum_rejected(self):
        with pytest.raises(ValidationError):
            clean_listing(_valid_raw(price_clp=5_000_000))

    def test_boolean_rejected_as_price(self):
        with pytest.raises(ValidationError):
            clean_listing(_valid_raw(price_clp=True))

    def test_unparseable_string_rejected(self):
        with pytest.raises(ValidationError):
            clean_listing(_valid_raw(price_clp="gratis"))


class TestM2Validation:
    def test_string_m2_coerced(self):
        assert clean_listing(_valid_raw(m2="75.5")).m2 == 75.5

    def test_below_min_rejected(self):
        with pytest.raises(ValidationError):
            clean_listing(_valid_raw(m2=5))

    def test_above_max_rejected(self):
        with pytest.raises(ValidationError):
            clean_listing(_valid_raw(m2=5000))

    def test_non_numeric_rejected(self):
        with pytest.raises(ValidationError):
            clean_listing(_valid_raw(m2="setenta y cinco"))

    def test_incomplete_mode_extracts_m2_from_title(self):
        result = clean_listing(
            _valid_raw(m2=0, title="Departamento 2D 1B 42 m2 en venta"),
            allow_incomplete=True,
        )
        assert result.m2 == 42
        assert "data_quality_warnings" not in result.raw_metadata

    def test_incomplete_mode_keeps_missing_m2_with_warning(self):
        result = clean_listing(_valid_raw(m2=0), allow_incomplete=True)
        assert result.m2 is None
        assert result.raw_metadata["data_quality"] == "incomplete"
        assert result.raw_metadata["data_quality_warnings"] == ["missing_m2"]

    def test_house_keeps_land_area_separate_from_built_area(self):
        result = clean_listing(
            _valid_raw(
                property_type="casa",
                m2=140,
                land_area_m2=500,
                title="Casa 140 m2 construidos terreno 500 m2 en Vitacura",
                comuna="vitacura",
            )
        )
        assert result.property_type == "house"
        assert result.built_area_m2 == 140
        assert result.land_area_m2 == 500

    def test_extracts_land_area_from_description_without_inventing_it(self):
        with_land = clean_listing(
            _valid_raw(
                property_type="casa",
                m2=120,
                description="Casa con 120 m2 construidos y terreno 360 m2",
            )
        )
        without_land = clean_listing(_valid_raw(property_type="casa", m2=120, description="Casa remodelada"))
        assert with_land.built_area_m2 == 120
        assert with_land.land_area_m2 == 360
        assert without_land.land_area_m2 is None

    @pytest.mark.parametrize(
        ("description", "expected_land"),
        [
            ("Casa remodelada con terreno 300 m2", 300),
            ("Casa remodelada con terreno 300 m²", 300),
            ("Casa con sup terreno 300", 300),
            ("Casa con superficie terreno 300 m2", 300),
            ("Casa con sitio 500 m2", 500),
            ("Casa con lote 400 m2", 400),
            ("Casa 140 construidos / 300 terreno", 300),
            ("Casa con 140 m2 construidos y 300 m2 terreno", 300),
            ("Casa 140/300 m2 en La Florida", 300),
            ("Casa con superficie total terreno 450 m2", 450),
            ("Casa con 300 m2 terreno", 300),
            ("Casa con 300 mts2 terreno", 300),
        ],
    )
    def test_extracts_new_house_land_area_patterns(self, description, expected_land):
        result = clean_listing(
            _valid_raw(
                property_type="casa",
                title="Casa amplia en La Florida",
                comuna="la_florida",
                m2=140,
                description=description,
            )
        )

        assert result.property_type == "house"
        assert result.built_area_m2 == 140
        assert result.land_area_m2 == expected_land
        assert result.raw_metadata["area_parse_version"] == "area_parser_v2"
        assert result.raw_metadata["land_area_parse_source"].startswith("text.")

    def test_area_parser_keeps_built_usable_and_land_separate(self):
        areas = extract_area_fields(
            {
                "property_type": "casa",
                "description": "Casa con 140 m2 construidos y 300 m2 terreno",
            },
            title="Casa en venta",
        )

        assert areas["built_area_m2"] == 140
        assert areas["land_area_m2"] == 300
        assert "usable_area_m2" not in areas

    def test_area_parse_metadata_preserves_existing_raw_metadata(self):
        result = clean_listing(
            _valid_raw(
                property_type="casa",
                title="Casa en La Florida",
                comuna="la_florida",
                m2=140,
                description="Casa con 140 m2 construidos y 300 m2 terreno",
                raw_metadata={"source_page": 7},
            )
        )

        assert result.raw_metadata["source_page"] == 7
        assert result.raw_metadata["area_parse_version"] == "area_parser_v2"
        assert result.raw_metadata["built_area_parse_source"] in {
            "raw.m2.fallback",
            "text.built_area_context",
        }
        assert result.raw_metadata["land_area_parse_source"] == "text.land_area_context"

    def test_area_parser_does_not_treat_listing_code_as_land_area(self):
        result = clean_listing(
            _valid_raw(
                property_type="casa",
                title="Venta De Casa Con Gran Terreno Solida. Cod. 4521",
                comuna="estacion_central",
                m2=140,
            )
        )

        assert result.land_area_m2 is None

    @pytest.mark.parametrize(
        ("description", "expected_land"),
        [
            ("Liquido terreno 1.000 m2 con 3 casas", 1000),
            ("Casa en parque con terreno de 5.432 m2", 5432),
            ("Casa con terreno 1.250,5 m2", 1250.5),
        ],
    )
    def test_area_parser_treats_dots_as_thousands_for_land_area(self, description, expected_land):
        result = clean_listing(
            _valid_raw(
                property_type="casa",
                title="Casa amplia en La Florida",
                comuna="la_florida",
                m2=140,
                description=description,
            )
        )

        assert result.land_area_m2 == expected_land
        assert result.built_area_m2 == 140

    def test_house_land_area_m2_does_not_feed_built_area_when_it_is_only_total_area(self):
        result = clean_listing(
            _valid_raw(
                property_type="casa",
                title="Casa con terreno 1.000 m2 en La Florida",
                comuna="la_florida",
                m2="1.000",
                land_area_m2="1.000",
            ),
            allow_incomplete=True,
        )

        assert result.property_type == "house"
        assert result.land_area_m2 == 1000
        assert result.built_area_m2 is None
        assert result.m2 is None
        assert "m2_identified_as_land_area" in result.raw_metadata["data_quality_warnings"]

    def test_area_parser_prefers_mts2_de_terreno_over_price_after_terreno(self):
        result = clean_listing(
            _valid_raw(
                property_type="casa",
                title="CASA EN VENTA, 242 mts2 DE TERRENO, ESTACION CENTRAL $195 MILLONES",
                comuna="estacion_central",
                m2=140,
            )
        )

        assert result.land_area_m2 == 242

    def test_incomplete_mode_keeps_unknown_comuna_with_warning(self):
        result = clean_listing(_valid_raw(title="Departamento amplio", comuna="Valparaíso"), allow_incomplete=True)
        assert result.comuna == "valparaiso"
        assert result.raw_metadata["data_quality_warnings"] == ["unknown_comuna"]

    def test_incomplete_mode_still_rejects_invalid_url(self):
        with pytest.raises(ValidationError, match="invalid_url"):
            clean_listing(_valid_raw(url=""), allow_incomplete=True)


class TestPropertyTypeDetection:
    def test_category_casa_maps_to_house(self):
        result = clean_listing(_valid_raw(title="Amplia propiedad en venta", category="Casas"))
        assert result.property_type == "house"

    def test_url_casa_maps_to_house(self):
        result = clean_listing(
            _valid_raw(
                title="Amplia propiedad en venta",
                url="https://www.yapo.cl/bienes-raices-venta-de-propiedades-casas/abc/123",
            )
        )
        assert result.property_type == "house"

    def test_description_casa_maps_to_house(self):
        result = clean_listing(_valid_raw(title="Propiedad remodelada", description="Casa aislada con jardin"))
        assert result.property_type == "house"

    def test_explicit_house_is_not_overridden_by_apartment_signals(self):
        result = clean_listing(
            _valid_raw(
                property_type="house",
                title="Departamento amplio en Nunoa",
                url="https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-amplio/123",
                raw_metadata={"category": "departamentos"},
            )
        )
        assert result.property_type == "house"

    def test_depto_maps_to_apartment(self):
        result = clean_listing(_valid_raw(title="Depto remodelado cerca de metro"))
        assert result.property_type == "apartment"

    def test_oficina_maps_to_office(self):
        result = clean_listing(_valid_raw(title="Oficina habilitada en Providencia", comuna="Providencia"))
        assert result.property_type == "office"

    def test_terreno_maps_to_land(self):
        result = clean_listing(_valid_raw(title="Terreno urbano en Nunoa", comuna="Nunoa"))
        assert result.property_type == "land"

    def test_unclear_type_falls_back_to_unknown(self):
        result = clean_listing(_valid_raw(title="Propiedad amplia en Nunoa", comuna="Nunoa"))
        assert result.property_type == "unknown"

    def test_house_slash_area_pair_maps_built_and_land(self):
        result = clean_listing(
            _valid_raw(
                title="Casa 140/500 m2 en Vitacura",
                comuna="Vitacura",
                m2=140,
            )
        )
        assert result.property_type == "house"
        assert result.built_area_m2 == 140
        assert result.land_area_m2 == 500

    def test_apartment_slash_area_pair_maps_usable_and_total_without_land(self):
        result = clean_listing(
            _valid_raw(
                title="Departamento 80/90 m2 en Nunoa",
                comuna="Nunoa",
                m2=80,
            )
        )
        assert result.property_type == "apartment"
        assert result.usable_area_m2 == 80
        assert result.built_area_m2 == 90
        assert result.land_area_m2 is None

    def test_no_land_area_when_house_has_no_land_signal(self):
        result = clean_listing(_valid_raw(title="Casa remodelada en Nunoa", comuna="Nunoa", m2=120))
        assert result.property_type == "house"
        assert result.built_area_m2 == 120
        assert result.land_area_m2 is None


class TestDiscreteFields:
    def test_float_bedrooms_coerced(self):
        assert clean_listing(_valid_raw(bedrooms=3.0)).bedrooms == 3

    def test_negative_parking_rejected(self):
        with pytest.raises(ValidationError):
            clean_listing(_valid_raw(parking=-1))

    def test_bedrooms_above_max_rejected(self):
        with pytest.raises(ValidationError):
            clean_listing(_valid_raw(bedrooms=99))


class TestRequiredFields:
    @pytest.mark.parametrize("missing", ["source", "title", "m2", "bedrooms", "bathrooms", "price_clp"])
    def test_missing_required_field_raises(self, missing):
        raw = _valid_raw()
        del raw[missing]
        with pytest.raises(ValidationError):
            clean_listing(raw)

    def test_empty_title_rejected(self):
        with pytest.raises(ValidationError):
            clean_listing(_valid_raw(title="   "))


class TestCoordinates:
    def test_none_lat_lon_returns_no_coords(self):
        raw = _valid_raw()
        del raw["lat"]
        del raw["lon"]
        assert clean_listing(raw).coordinates is None

    def test_only_one_coord_returns_none(self):
        raw = _valid_raw(lat=None)
        assert clean_listing(raw).coordinates is None

    def test_invalid_coords_raises(self):
        with pytest.raises(ValidationError):
            clean_listing(_valid_raw(lat=999))

    def test_non_numeric_coords_raises(self):
        with pytest.raises(ValidationError):
            clean_listing(_valid_raw(lat="norte"))

    def test_address_precision_without_coordinates_degrades_to_street(self):
        raw = _valid_raw(
            lat=None,
            lon=None,
            raw_metadata={
                "geocode_precision": "address",
                "address_label": "Avenida Portugal",
            },
        )

        assert clean_listing(raw).geocode_precision == "street"
