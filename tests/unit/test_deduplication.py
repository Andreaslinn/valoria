"""Tests unitarios de make_fingerprint."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from core.value_objects.price import Price
from domain.ingestion.data_cleaning import CleanedListing
from domain.ingestion.deduplication import make_fingerprint


def _cleaned(**overrides) -> CleanedListing:
    defaults = {
        "source": "yapo",
        "external_id": None,
        "title": "Depto 3D/2B en Ñuñoa",
        "comuna": "nunoa",
        "m2": 75.0,
        "bedrooms": 3,
        "bathrooms": 2,
        "parking": 1,
        "price": Price(clp=Decimal("180000000")),
        "scraped_at": datetime(2026, 4, 23, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return CleanedListing(**defaults)


class TestDeterminism:
    def test_same_input_same_fingerprint(self):
        a = make_fingerprint(_cleaned())
        b = make_fingerprint(_cleaned())
        assert a == b

    def test_fingerprint_is_40_char_hex(self):
        fp = make_fingerprint(_cleaned())
        assert len(fp) == 40
        assert all(c in "0123456789abcdef" for c in fp)


class TestTitleNormalization:
    def test_word_order_does_not_matter(self):
        """Los tokens se ordenan: mismo conjunto → mismo fingerprint."""
        a = make_fingerprint(_cleaned(title="Hermoso Depto Centro Ñuñoa"))
        b = make_fingerprint(_cleaned(title="Ñuñoa Centro Depto Hermoso"))
        assert a == b

    def test_case_insensitive(self):
        a = make_fingerprint(_cleaned(title="DEPTO en nunoa"))
        b = make_fingerprint(_cleaned(title="depto EN Nunoa"))
        assert a == b

    def test_accents_ignored(self):
        a = make_fingerprint(_cleaned(title="Depto en Ñuñoa Centro"))
        b = make_fingerprint(_cleaned(title="Depto en Nunoa Centro"))
        assert a == b

    def test_short_tokens_ignored(self):
        """'en', 'la', etc. (<3 chars) no cuentan → agregar/quitar no cambia el hash."""
        a = make_fingerprint(_cleaned(title="Depto Ñuñoa Centro"))
        b = make_fingerprint(_cleaned(title="Un Depto en la Ñuñoa de Centro"))
        assert a == b


class TestM2Rounding:
    def test_small_m2_variations_equivalent(self):
        """75.0 y 74.8 redondean a 75 → mismo fingerprint."""
        a = make_fingerprint(_cleaned(m2=75.0))
        b = make_fingerprint(_cleaned(m2=74.8))
        assert a == b

    def test_round_half_to_even_chile(self):
        # 75.5 → 76 (banker's rounding de Python), 76.0 → 76 → iguales
        a = make_fingerprint(_cleaned(m2=75.5))
        b = make_fingerprint(_cleaned(m2=76.0))
        assert a == b

    def test_large_m2_diff_differ(self):
        a = make_fingerprint(_cleaned(m2=75))
        b = make_fingerprint(_cleaned(m2=90))
        assert a != b


class TestAttributeDifferences:
    def test_different_comuna_differs(self):
        a = make_fingerprint(_cleaned(comuna="nunoa"))
        b = make_fingerprint(_cleaned(comuna="providencia"))
        assert a != b

    def test_different_bedrooms_differs(self):
        a = make_fingerprint(_cleaned(bedrooms=3))
        b = make_fingerprint(_cleaned(bedrooms=2))
        assert a != b

    def test_different_bathrooms_differs(self):
        a = make_fingerprint(_cleaned(bathrooms=2))
        b = make_fingerprint(_cleaned(bathrooms=3))
        assert a != b

    def test_different_parking_differs(self):
        a = make_fingerprint(_cleaned(parking=1))
        b = make_fingerprint(_cleaned(parking=2))
        assert a != b


class TestSourceAgnostic:
    def test_same_listing_different_source_same_fingerprint(self):
        """El fingerprint NO usa source — mismo inmueble en yapo y portal → duplicado."""
        a = make_fingerprint(_cleaned(source="yapo"))
        b = make_fingerprint(_cleaned(source="portalinmobiliario"))
        assert a == b

    def test_price_not_in_fingerprint(self):
        """Cambios de precio no cambian el fingerprint (el pipeline los actualiza)."""
        a = make_fingerprint(_cleaned(price=Price(clp=Decimal("180000000"))))
        b = make_fingerprint(_cleaned(price=Price(clp=Decimal("200000000"))))
        assert a == b
