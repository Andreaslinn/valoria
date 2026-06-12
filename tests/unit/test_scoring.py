"""Tests unitarios de la función de similitud."""
from __future__ import annotations

from core.value_objects.location import Coordinates
from domain.valuation.scoring import similarity_score
from tests.unit.factories import make_listing, make_property


class TestExactMatch:
    def test_identical_properties_score_1(self):
        target = make_property()
        candidate = make_listing()  # mismos valores
        assert similarity_score(target, candidate).value == 1.0


class TestM2Component:
    def test_larger_m2_lowers_score(self):
        target = make_property(m2=75.0)
        near = make_listing(fingerprint="a", m2=75.0)
        far = make_listing(fingerprint="b", m2=100.0)
        assert similarity_score(target, near).value > similarity_score(target, far).value

    def test_50pct_m2_diff_reduces_score(self):
        target = make_property(m2=100.0)
        similar = make_listing(fingerprint="sim", m2=100.0)
        diff = make_listing(fingerprint="diff", m2=150.0)
        assert similarity_score(target, similar).value > similarity_score(target, diff).value

    def test_property_type_mismatch_scores_zero(self):
        target = make_property(property_type="house", m2=140, built_area_m2=140, land_area_m2=300)
        apartment = make_listing(fingerprint="apt", property_type="apartment", m2=140)
        assert similarity_score(target, apartment).value == 0.0

    def test_house_land_area_affects_score_strongly(self):
        target = make_property(property_type="house", m2=140, built_area_m2=140, land_area_m2=500)
        same_land = make_listing(
            fingerprint="same_land",
            property_type="house",
            m2=140,
            built_area_m2=140,
            land_area_m2=500,
        )
        different_land = make_listing(
            fingerprint="different_land",
            property_type="house",
            m2=140,
            built_area_m2=140,
            land_area_m2=120,
        )
        assert similarity_score(target, same_land).value > similarity_score(target, different_land).value

    def test_house_missing_land_area_still_scores_but_lower(self):
        target = make_property(property_type="house", m2=140, built_area_m2=140, land_area_m2=500)
        complete = make_listing(
            fingerprint="complete",
            property_type="house",
            m2=140,
            built_area_m2=140,
            land_area_m2=500,
        )
        missing_land = make_listing(
            fingerprint="missing_land",
            property_type="house",
            m2=140,
            built_area_m2=140,
            land_area_m2=None,
        )
        assert similarity_score(target, missing_land).value > 0
        assert similarity_score(target, complete).value > similarity_score(target, missing_land).value


class TestDistanceComponent:
    def test_same_location_gives_max_distance_score(self):
        target = make_property(coords=Coordinates(-33.45, -70.59))
        same = make_listing(coords=Coordinates(-33.45, -70.59))
        assert similarity_score(target, same).value == 1.0

    def test_missing_coords_is_neutral_not_zero(self):
        target = make_property(coords=None)
        with_coords = make_listing(fingerprint="a", coords=Coordinates(-33.45, -70.59))
        without_coords = make_listing(fingerprint="b", coords=None)
        # El de sin coords debería ser exacto en todo lo demás → score alto.
        # El de con coords tiene la distancia penalizada (neutra).
        assert similarity_score(target, without_coords).value >= similarity_score(
            target, with_coords
        ).value

    def test_far_listing_scores_lower_than_near(self):
        target = make_property(coords=Coordinates(-33.45, -70.59))
        near = make_listing(fingerprint="a", coords=Coordinates(-33.451, -70.591))
        far = make_listing(fingerprint="b", coords=Coordinates(-33.49, -70.65))
        assert similarity_score(target, near).value > similarity_score(target, far).value

    def test_comuna_centroid_distance_is_degraded(self):
        target = make_property(coords=Coordinates(-33.45, -70.59))
        exact = make_listing(
            fingerprint="exact",
            coords=Coordinates(-33.45, -70.59),
            geocode_precision="exact",
        )
        centroid = make_listing(
            fingerprint="centroid",
            coords=Coordinates(-33.45, -70.59),
            geocode_precision="comuna_centroid",
        )
        assert similarity_score(target, exact).value > similarity_score(target, centroid).value

    def test_street_precision_has_weaker_distance_impact_than_address(self):
        target = make_property(coords=Coordinates(-33.45, -70.59), geocode_precision="exact")
        address_near = make_listing(
            fingerprint="address_near",
            coords=Coordinates(-33.451, -70.591),
            geocode_precision="address",
        )
        street_near = make_listing(
            fingerprint="street_near",
            coords=Coordinates(-33.451, -70.591),
            geocode_precision="street",
        )

        assert similarity_score(target, address_near).value > similarity_score(target, street_near).value

    def test_comuna_precision_does_not_pretend_same_coordinates_are_exact(self):
        target = make_property(coords=Coordinates(-33.45, -70.59), geocode_precision="exact")
        exact_same = make_listing(
            fingerprint="exact_same",
            coords=Coordinates(-33.45, -70.59),
            geocode_precision="exact",
        )
        comuna_same = make_listing(
            fingerprint="comuna_same",
            coords=Coordinates(-33.45, -70.59),
            geocode_precision="comuna",
        )

        assert similarity_score(target, exact_same).value > similarity_score(target, comuna_same).value

    def test_unknown_precision_is_neutral_even_with_coordinates(self):
        target = make_property(coords=Coordinates(-33.45, -70.59), geocode_precision="exact")
        unknown_near = make_listing(
            fingerprint="unknown_near",
            coords=Coordinates(-33.45, -70.59),
            geocode_precision="unknown",
        )
        unknown_far = make_listing(
            fingerprint="unknown_far",
            coords=Coordinates(-33.49, -70.65),
            geocode_precision="unknown",
        )

        assert similarity_score(target, unknown_near).value == similarity_score(target, unknown_far).value

    def test_comuna_precision_disables_distance_even_with_same_coordinates(self):
        target = make_property(coords=Coordinates(-33.45, -70.59), geocode_precision="comuna")
        comuna_near = make_listing(
            fingerprint="comuna_near",
            coords=Coordinates(-33.45, -70.59),
            geocode_precision="comuna",
        )
        comuna_far = make_listing(
            fingerprint="comuna_far",
            coords=Coordinates(-33.49, -70.65),
            geocode_precision="comuna",
        )

        assert similarity_score(target, comuna_near).value == similarity_score(target, comuna_far).value


class TestDiscreteComponents:
    def test_different_bedrooms_lowers_score(self):
        target = make_property(bedrooms=3)
        same = make_listing(fingerprint="a", bedrooms=3)
        diff = make_listing(fingerprint="b", bedrooms=5)
        assert similarity_score(target, same).value > similarity_score(target, diff).value

    def test_different_bathrooms_lowers_score(self):
        target = make_property(bathrooms=2)
        same = make_listing(fingerprint="a", bathrooms=2)
        diff = make_listing(fingerprint="b", bathrooms=4)
        assert similarity_score(target, same).value > similarity_score(target, diff).value

    def test_different_parking_lowers_score(self):
        target = make_property(parking=1)
        same = make_listing(fingerprint="a", parking=1)
        diff = make_listing(fingerprint="b", parking=3)
        assert similarity_score(target, same).value > similarity_score(target, diff).value


class TestBounds:
    def test_score_always_in_unit_interval(self):
        target = make_property(m2=10.0, bedrooms=1, bathrooms=1, parking=0)
        extreme = make_listing(
            m2=500.0, bedrooms=8, bathrooms=6, parking=10,
            coords=Coordinates(33.45, 70.59),  # al otro lado del mundo
        )
        score = similarity_score(target, extreme).value
        assert 0.0 <= score <= 1.0
