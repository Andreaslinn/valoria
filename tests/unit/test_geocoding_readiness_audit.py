from scripts.geocode_listings import extract_address_candidate
from scripts.geocoding_readiness_audit import classify_listing_readiness, classify_textual_readiness


def _row(**overrides):
    row = {
        "id": 1,
        "title": "Departamento en Avenida Vicuna Mackenna 1234",
        "url": "https://example.com/departamento-en-avenida-vicuna-mackenna-1234",
        "comuna": "santiago",
        "property_type": "apartment",
        "lat": None,
        "lon": None,
        "geocode_precision": "unknown",
        "status": "active",
        "raw_metadata": {},
    }
    row.update(overrides)
    return row


def test_classifies_address_number_as_text_address_recoverable() -> None:
    readiness = classify_listing_readiness(_row())

    assert readiness.text_class == "text_address_recoverable"
    assert readiness.is_backfill_candidate is True


def test_classifies_intersection_as_probable_intersection() -> None:
    readiness = classify_listing_readiness(
        _row(title="Depto Pedro de Valdivia con Irarrazaval", raw_metadata={})
    )

    assert readiness.text_class == "probable_intersection"


def test_classifies_metro_as_landmark_or_metro() -> None:
    readiness = classify_listing_readiness(
        _row(title="Departamento a pasos de Metro Parque Almagro", raw_metadata={})
    )

    assert readiness.text_class == "probable_landmark_or_metro"


def test_rejects_marketing_text_as_impossible() -> None:
    readiness = classify_listing_readiness(
        _row(
            title="Gran oportunidad amplia casa",
            url="",
            property_type="house",
            raw_metadata={"description": "casa y piscina sector residencial"},
        )
    )

    assert readiness.text_class == "impossible"
    assert readiness.is_backfill_candidate is False


def test_address_level_coords_are_not_backfill_candidates() -> None:
    readiness = classify_listing_readiness(
        _row(lat=-33.45, lon=-70.6, geocode_precision="address")
    )

    assert readiness.coords_class == "address_level_coords"
    assert readiness.is_backfill_candidate is False


def test_raw_metadata_address_label_is_used() -> None:
    candidate = extract_address_candidate(
        title="Departamento moderno",
        description="",
        url="",
        comuna="nunoa",
        raw_metadata={"address_label": "Av. Pedro de Valdivia 2500"},
    )

    assert candidate.text
    assert classify_textual_readiness(candidate, _empty_signals()) == "text_address_recoverable"


def test_readiness_outputs_canonical_candidate_precision() -> None:
    readiness = classify_listing_readiness(_row(title="Departamento a pasos de Metro Parque Almagro"))

    assert readiness.text_class == "probable_landmark_or_metro"
    assert readiness.candidate_precision == "street"


def _empty_signals():
    class Signals:
        nearby_metro = None
        nearby_avenue = None
        intersection_hint = None
        landmark_tokens = ()

    return Signals()
