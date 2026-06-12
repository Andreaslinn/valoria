from __future__ import annotations

from core.normalization.geocode_precision import (
    CANONICAL_GEOCODE_PRECISIONS,
    canonical_geocode_precision,
    geocode_precision_rank,
    normalize_geocode_precision,
)


def test_canonical_labels_are_explicit() -> None:
    assert CANONICAL_GEOCODE_PRECISIONS == {"address", "street", "comuna", "comuna_centroid", "unknown"}


def test_legacy_exact_aliases_to_address() -> None:
    assert canonical_geocode_precision("exact") == "address"
    assert canonical_geocode_precision("street_address") == "address"
    assert normalize_geocode_precision("exact", has_coords=True, raw_metadata={}, comuna="nunoa") == "address"


def test_address_level_without_coordinates_is_capped_by_evidence() -> None:
    assert (
        normalize_geocode_precision(
            "address",
            has_coords=False,
            raw_metadata={"address_label": "Avenida Portugal"},
            comuna="santiago",
        )
        == "street"
    )
    assert normalize_geocode_precision("address", has_coords=False, raw_metadata={}, comuna="santiago") == "comuna"


def test_comuna_with_coordinates_is_centroid_not_address() -> None:
    assert normalize_geocode_precision("comuna", has_coords=True, raw_metadata={}, comuna="santiago") == "comuna_centroid"


def test_rank_never_allows_comuna_to_beat_address_level_alias() -> None:
    assert geocode_precision_rank("exact") == geocode_precision_rank("address")
    assert geocode_precision_rank("address") > geocode_precision_rank("comuna")
    assert geocode_precision_rank("address") > geocode_precision_rank("comuna_centroid")
