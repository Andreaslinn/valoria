"""Tests unitarios del detector de oportunidades del radar."""
from __future__ import annotations

from decimal import Decimal

from domain.radar.detector import detect_opportunities
from tests.unit.factories import make_listing

UF = Decimal("37000")

# Precio base del mercado: 2.4M CLP/m2 x 75 m2 = 180M
_MARKET_PRICE = 180_000_000


def _market_listings(n: int, *, fp_prefix: str = "m") -> list:
    """n listings uniformes al precio de mercado en Ñuñoa."""
    return [make_listing(fingerprint=f"{fp_prefix}{i}", price_clp=_MARKET_PRICE) for i in range(n)]


class TestInsufficientDataset:
    def test_empty_listings_returns_empty_low_data(self):
        result = detect_opportunities([], UF)
        assert result.opportunities == []
        assert result.total_listings_analyzed == 0
        assert result.low_data_mode is True

    def test_below_min_dataset_returns_empty(self):
        """Con < MIN_RADAR_DATASET_SIZE (10) listings no se evalúa nada."""
        result = detect_opportunities(_market_listings(9), UF)
        assert result.opportunities == []
        assert result.low_data_mode is True

    def test_non_active_listings_do_not_count_towards_min(self):
        listings = [
            make_listing(fingerprint=f"s{i}", status="sold") for i in range(20)
        ]
        result = detect_opportunities(listings, UF)
        assert result.total_listings_analyzed == 0
        assert result.opportunities == []


class TestLowDataMode:
    def test_10_to_49_triggers_low_data_mode(self):
        result = detect_opportunities(_market_listings(15), UF)
        assert result.low_data_mode is True
        assert result.total_listings_analyzed == 15

    def test_50_plus_is_normal_mode(self):
        result = detect_opportunities(_market_listings(50), UF)
        assert result.low_data_mode is False
        assert result.total_listings_analyzed == 50
        assert result.low_data_by_property_type == {"apartment": False}

    def test_global_dataset_sufficient_but_houses_insufficient_marks_house_low_data(self):
        apartments = _market_listings(50)
        houses = [
            make_listing(
                fingerprint=f"house-{idx}",
                property_type="house",
                m2=140,
                built_area_m2=140,
                land_area_m2=400,
            )
            for idx in range(4)
        ]

        result = detect_opportunities([*apartments, *houses], UF)

        assert result.low_data_mode is True
        assert result.low_data_by_property_type["apartment"] is False
        assert result.low_data_by_property_type["house"] is True

    def test_houses_sufficient_do_not_depend_on_apartments(self):
        houses = [
            make_listing(
                fingerprint=f"house-{idx}",
                property_type="house",
                m2=140,
                built_area_m2=140,
                land_area_m2=400,
            )
            for idx in range(50)
        ]

        result = detect_opportunities(houses, UF)

        assert result.low_data_mode is False
        assert result.low_data_by_property_type == {"house": False}

    def test_7pct_undervalue_not_flagged_in_low_data_mode(self):
        """Con 15 listings (low-data), un descuento de 7 % NO califica (umbral 10 %)."""
        cheap = make_listing(
            fingerprint="cheap",
            price_clp=int(_MARKET_PRICE * 0.93),  # 7 % debajo del mercado
        )
        listings = [*_market_listings(14), cheap]
        result = detect_opportunities(listings, UF)
        assert result.low_data_mode is True
        assert all(o.listing.fingerprint != "cheap" for o in result.opportunities)

    def test_12pct_undervalue_flagged_in_low_data_mode(self):
        cheap = make_listing(
            fingerprint="cheap",
            price_clp=int(_MARKET_PRICE * 0.88),  # 12 % debajo
        )
        listings = [*_market_listings(14), cheap]
        result = detect_opportunities(listings, UF)
        fingerprints = {o.listing.fingerprint for o in result.opportunities}
        assert "cheap" in fingerprints

    def test_7pct_undervalue_flagged_in_normal_mode(self):
        """Con 50+ listings (normal), un descuento de 7 % SÍ califica (umbral 5 %)."""
        cheap = make_listing(
            fingerprint="cheap",
            price_clp=int(_MARKET_PRICE * 0.93),
        )
        listings = [*_market_listings(49), cheap]
        result = detect_opportunities(listings, UF)
        assert result.low_data_mode is False
        fingerprints = {o.listing.fingerprint for o in result.opportunities}
        assert "cheap" in fingerprints


class TestOverpriced:
    def test_overpriced_listing_is_not_flagged(self):
        expensive = make_listing(
            fingerprint="expensive",
            price_clp=int(_MARKET_PRICE * 1.15),  # 15 % sobreprecio
        )
        listings = [*_market_listings(50), expensive]
        result = detect_opportunities(listings, UF)
        fingerprints = {o.listing.fingerprint for o in result.opportunities}
        assert "expensive" not in fingerprints

    def test_market_priced_listing_is_not_flagged(self):
        target = make_listing(fingerprint="target", price_clp=_MARKET_PRICE)
        listings = [*_market_listings(50), target]
        result = detect_opportunities(listings, UF)
        fingerprints = {o.listing.fingerprint for o in result.opportunities}
        assert "target" not in fingerprints


class TestOpportunityContent:
    def test_opportunity_fields_populated_correctly(self):
        cheap = make_listing(
            fingerprint="cheap",
            price_clp=int(_MARKET_PRICE * 0.85),  # 15 % debajo
        )
        listings = [*_market_listings(50), cheap]
        result = detect_opportunities(listings, UF)

        found = next(o for o in result.opportunities if o.listing.fingerprint == "cheap")
        assert found.market_price.clp == Decimal(_MARKET_PRICE)
        assert 0.14 <= found.discount_pct <= 0.16  # ≈ 15 %
        assert found.comparables_used >= 5
        assert 0.0 <= found.confidence.value <= 1.0
        assert found.valuation_result is not None
        assert found.valuation_result.estimated_price == found.market_price
        assert found.valuation_result.comparables_used == found.comparables_used

    def test_uf_listing_uses_canonical_uf_for_discount(self):
        target = make_listing(
            fingerprint="uf-cheap",
            price_clp=999_000_000,
            price_currency="UF",
            price_uf=4500,
            price_uf_source="scraped",
        )
        listings = [*_market_listings(50), target]

        result = detect_opportunities(listings, UF)

        found = next(o for o in result.opportunities if o.listing.fingerprint == "uf-cheap")
        assert found.price_basis_used == "uf"
        assert found.price_data_quality == "scraped"
        assert found.price_uf == Decimal("4500.00")
        assert found.price_clp_snapshot == Decimal("999000000")
        assert 0.07 <= found.discount_pct <= 0.08

    def test_uf_legacy_without_price_uf_does_not_generate_strong_opportunity(self):
        target = make_listing(
            fingerprint="legacy-uf",
            price_clp=int(_MARKET_PRICE * 0.80),
            price_currency="UF",
            price_uf_source="legacy_unrecoverable",
        )
        listings = [*_market_listings(50), target]

        result = detect_opportunities(listings, UF)

        assert all(o.listing.fingerprint != "legacy-uf" for o in result.opportunities)

    def test_estimated_uf_price_does_not_generate_strong_opportunity(self):
        target = make_listing(
            fingerprint="estimated-uf",
            price_clp=int(_MARKET_PRICE * 0.80),
            price_currency="UF",
            price_uf=Decimal(_MARKET_PRICE) / UF * Decimal("0.80"),
            price_uf_source="estimated",
            price_uf_confidence="low",
        )
        listings = [*_market_listings(50), target]

        result = detect_opportunities(listings, UF)

        assert all(o.listing.fingerprint != "estimated-uf" for o in result.opportunities)

    def test_clp_listing_uses_clp_basis(self):
        target = make_listing(
            fingerprint="clp-cheap",
            price_clp=int(_MARKET_PRICE * 0.90),
            price_currency="CLP",
        )
        listings = [*_market_listings(50), target]

        result = detect_opportunities(listings, UF)

        found = next(o for o in result.opportunities if o.listing.fingerprint == "clp-cheap")
        assert found.price_basis_used == "clp"
        assert found.price_data_quality == "canonical_clp"
        assert 0.09 <= found.discount_pct <= 0.11

    def test_clp_false_positive_no_longer_crosses_when_uf_is_not_discounted(self):
        market_price_uf = Decimal(_MARKET_PRICE) / UF
        target = make_listing(
            fingerprint="uf-not-cheap",
            price_clp=int(_MARKET_PRICE * 0.88),
            price_currency="UF",
            price_uf=(market_price_uf * Decimal("1.01")).quantize(Decimal("0.01")),
            price_uf_source="scraped",
        )
        listings = [*_market_listings(50), target]

        result = detect_opportunities(listings, UF)

        assert all(o.listing.fingerprint != "uf-not-cheap" for o in result.opportunities)

    def test_ranking_score_equals_discount_times_confidence(self):
        cheap = make_listing(
            fingerprint="cheap",
            price_clp=int(_MARKET_PRICE * 0.80),
        )
        listings = [*_market_listings(50), cheap]
        result = detect_opportunities(listings, UF)
        opp = result.opportunities[0]
        assert opp.ranking_score == opp.discount_pct * opp.confidence.value

    def test_house_opportunity_uses_house_comparables_not_apartments(self):
        house_market_price = 700_000_000
        apartment_market_price = 180_000_000
        cheap_house = make_listing(
            fingerprint="cheap-house",
            property_type="house",
            m2=140,
            built_area_m2=140,
            land_area_m2=400,
            price_clp=int(house_market_price * 0.85),
        )
        house_market = [
            make_listing(
                fingerprint=f"house-market-{idx}",
                property_type="house",
                m2=140,
                built_area_m2=140,
                land_area_m2=400,
                price_clp=house_market_price,
            )
            for idx in range(14)
        ]
        apartment_market = [
            make_listing(
                fingerprint=f"apt-market-{idx}",
                property_type="apartment",
                m2=140,
                price_clp=apartment_market_price,
            )
            for idx in range(20)
        ]

        result = detect_opportunities([cheap_house, *house_market, *apartment_market], UF)

        found = next(o for o in result.opportunities if o.listing.fingerprint == "cheap-house")
        assert found.market_price.clp == Decimal(house_market_price)
        assert found.comparables_used == 14

    def test_radar_does_not_backfill_house_comparables_with_apartments(self):
        cheap_house = make_listing(
            fingerprint="cheap-house",
            property_type="house",
            m2=140,
            built_area_m2=140,
            land_area_m2=400,
            price_clp=100_000_000,
        )
        apartment_market = [
            make_listing(
                fingerprint=f"apt-market-{idx}",
                property_type="apartment",
                m2=140,
                price_clp=700_000_000,
            )
            for idx in range(20)
        ]

        result = detect_opportunities([cheap_house, *apartment_market], UF)

        assert all(o.listing.fingerprint != "cheap-house" for o in result.opportunities)

    def test_house_with_few_same_type_rows_uses_low_data_threshold_even_when_global_is_large(self):
        house_market_price = 700_000_000
        cheap_house = make_listing(
            fingerprint="cheap-house",
            property_type="house",
            m2=140,
            built_area_m2=140,
            land_area_m2=400,
            price_clp=int(house_market_price * 0.93),
        )
        house_market = [
            make_listing(
                fingerprint=f"house-market-{idx}",
                property_type="house",
                m2=140,
                built_area_m2=140,
                land_area_m2=400,
                price_clp=house_market_price,
            )
            for idx in range(14)
        ]
        apartment_market = _market_listings(50, fp_prefix="apt-market")

        result = detect_opportunities([cheap_house, *house_market, *apartment_market], UF)

        assert result.low_data_by_property_type["house"] is True
        assert result.low_data_by_property_type["apartment"] is False
        assert all(o.listing.fingerprint != "cheap-house" for o in result.opportunities)

    def test_unknown_radar_listing_does_not_mix_with_apartments(self):
        cheap_unknown = make_listing(
            fingerprint="cheap-unknown",
            property_type="unknown",
            m2=75,
            price_clp=100_000_000,
        )
        apartment_market = [
            make_listing(
                fingerprint=f"apt-market-{idx}",
                property_type="apartment",
                m2=75,
                price_clp=180_000_000,
            )
            for idx in range(20)
        ]

        result = detect_opportunities([cheap_unknown, *apartment_market], UF)

        assert all(o.listing.fingerprint != "cheap-unknown" for o in result.opportunities)


class TestOrdering:
    def test_results_sorted_by_ranking_score_desc(self):
        discounts = [0.10, 0.25, 0.15, 0.30, 0.08]
        cheap_listings = [
            make_listing(fingerprint=f"c{i}", price_clp=int(_MARKET_PRICE * (1 - d)))
            for i, d in enumerate(discounts)
        ]
        listings = _market_listings(50) + cheap_listings
        result = detect_opportunities(listings, UF)

        scores = [o.ranking_score for o in result.opportunities]
        assert scores == sorted(scores, reverse=True)


class TestSelfExclusion:
    def test_target_not_in_its_own_candidates(self):
        """El listing evaluado no debe contarse como comparable de sí mismo.

        Con 1 cheap + 10 market, si el cheap fuera candidato de sí mismo,
        distorsionaría el estimado. Verificamos que se detecta como oportunidad
        limpia usando los otros 10.
        """
        cheap = make_listing(
            fingerprint="cheap",
            price_clp=int(_MARKET_PRICE * 0.80),  # 20 % debajo
        )
        listings = [*_market_listings(50), cheap]
        result = detect_opportunities(listings, UF)

        found = next(o for o in result.opportunities if o.listing.fingerprint == "cheap")
        # Si el cheap se incluyera como su propio comparable, el mercado estimado
        # bajaría y el descuento aparente sería menor a 20 %. Tolerancia ±2 %.
        assert 0.18 <= found.discount_pct <= 0.22


class TestUFRatePassthrough:
    def test_uf_rate_not_used_for_detection_but_accepted(self):
        """La tasa UF no afecta quién se detecta (el algoritmo es en CLP),
        pero debe aceptarse como parámetro para propagarla al ValuationResult."""
        cheap = make_listing(fingerprint="cheap", price_clp=int(_MARKET_PRICE * 0.80))
        listings = [*_market_listings(50), cheap]

        r1 = detect_opportunities(listings, Decimal("37000"))
        r2 = detect_opportunities(listings, Decimal("40000"))

        fps1 = {o.listing.fingerprint for o in r1.opportunities}
        fps2 = {o.listing.fingerprint for o in r2.opportunities}
        assert fps1 == fps2
